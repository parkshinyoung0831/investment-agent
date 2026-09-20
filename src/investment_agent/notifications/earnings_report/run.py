"""관심종목 신규 공시를 펀더멘탈 PNG와 축별 세그먼트 embed로 알린다.

발송처는 **포럼**이다 — 같은 종목의 공시를 스레드 하나에 누적하고 섹터 태그가 붙는다.
관심종목 50개가 분기마다 2주에 몰려도 종목별 기록을 한곳에서 이어 읽을 수 있다.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from collections.abc import Sequence
from pathlib import Path

from investment_agent.platform.logging import get_logger
from investment_agent.config import load_config
from investment_agent.notifications.earnings_report import candidates, render
from investment_agent.reporting.notifications import earnings_report as db
from investment_agent.notifications.earnings_report import card, embeds
from investment_agent.reporting.services.earnings import valuation_history as history
from investment_agent.notifications.channels.contracts import ForumThread
from investment_agent.notifications.context import default_context
from investment_agent.notifications.engine import PublishContext, Rendered, publish
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.notifications.channels import routing
from investment_agent.notifications.channels.directory import guild_directory
from investment_agent.platform.logging import configure_logging

log = get_logger(__name__)


def _forum_tags(target: str, item: dict, config) -> tuple[str, ...]:
    """업종·구간 태그를 이름에서 snowflake로 바꾼다.

    Discord는 태그를 이름이 아니라 ID로 받는다. 못 찾으면 태그 없이 보낸다 —
    분류 하나 때문에 카드를 통째로 막지 않는다.
    """
    # 업종은 `universe.entities.sic_division_name`이 유일한 기준이고, read model이
    # 그것을 `names.sic_division`으로 실어 준다(규칙 13).
    profile = item.get("names") or {}
    names = routing.tags_for(profile.get("sic_division"), item["row"].get("fiscal_period"))
    if not names:
        return ()
    try:
        directory = guild_directory(config)
    except Exception:  # noqa: BLE001 - 태그 실패가 발송을 막지 않는다
        log.warning("discord 길드 조회 실패 — 태그 없이 보낸다")
        return ()
    return tuple(directory.tag_ids_by_channel_id(target, tuple(names)))


def _persist_png(path: str, ticker: str, accession_no: str) -> str:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(path)
    target = Path("artifacts") / "notifications" / "earnings_report" / f"{ticker}_{accession_no}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target)


def _extras_by_ticker(tickers: list[str]) -> dict[str, dict]:
    """역사 밸류·건전성·이익의 질 계산에 필요한 데이터를 티커별로 한 번만 읽는다."""
    if not tickers:
        return {}
    prices = db.load_price_history(tickers)
    shares = db.load_shares_history(tickers)
    snapshots = db.load_valuation_snapshots(tickers)
    quality_history = db.load_quality_history(tickers)
    earnings_quality = db.load_earnings_quality(tickers)
    # 관측 컨센서스와 시점 결합 서프라이즈 이력은 한 번에 읽고 티커별로 나눈다.
    consensus_rows: dict[str, list[dict]] = {}
    for row in db.load_earnings_estimates(tickers):
        consensus_rows.setdefault(str(row["ticker"]), []).append(row)
    surprise_history = db.load_surprise_history(tickers)
    price_targets: dict[str, list[dict]] = {}
    for row in db.load_price_targets(tickers):
        price_targets.setdefault(str(row["ticker"]), []).append(row)
    out: dict[str, dict] = {}
    for ticker in tickers:
        raw_prices = prices.get(ticker, [])
        price_pairs = [
            (row["trade_date"], float(row["close"]))
            for row in raw_prices if row.get("close") is not None
        ]
        splits = [
            (str(row["trade_date"]), float(row["split_ratio"]))
            for row in raw_prices
            if row.get("split_ratio") is not None and float(row["split_ratio"]) > 0
        ]
        out[ticker] = {
            "hist": history.compute(
                price_pairs,
                shares.get(ticker, []),
                snapshots.get(ticker, []),
                splits=splits,
            ),
            "quality_history": quality_history.get(ticker, []),
            "eq": earnings_quality.get(ticker),
            "prices": raw_prices,
            "shares": shares.get(ticker, []),
            "earnings_estimates": consensus_rows.get(ticker, []),
            "surprise_history": surprise_history.get(ticker, []),
            "price_targets": price_targets.get(ticker, []),
        }
    return out


def run(
    *,
    tickers: set[str] | None = None,
    target: str | None = None,
    context: PublishContext | None = None,
) -> int:
    """준비된 최근 공시의 정밀 카드를 원장에 맡긴다. PNG는 원장이 이 실행에 맡긴 공시만 그린다.

    실시간 감시 경로는 방금 감지한 종목만 넘겨, 무관한 대기 공시의 렌더가
    발표 직후 카드 전송을 지연시키지 않게 한다.
    """
    items = candidates.load_ready_filings(tickers)
    if not items:
        log.info("fundamentals: 카드로 보낼 준비가 된 최근 공시 없음")
        return 0
    config = load_config()
    forum = discord_target(candidates.TOPIC.channel_kind, config=config, override=target)
    extras: dict[str, dict] = {}

    def render_card(batch):
        notice, = batch
        item = notice.data
        ticker = notice.subject
        if ticker not in extras:
            extras.update(_extras_by_ticker([ticker]))
        ctx, caption = card.build(item, extras.get(ticker))
        png = _persist_png(
            asyncio.run(render.shoot_png(render.render("earnings.html.j2", ctx))), ticker, notice.occurrence,
        )
        return Rendered(
            {"content": caption, "embeds": embeds.build_segments(item)},
            attachment_path=png,
            thread=ForumThread(ticker, routing.thread_title(ctx), _forum_tags(forum, item, config)),
        )

    report = publish(
        candidates.TOPIC,
        [candidates.filing_notice(item["row"], item) for item in items],
        render_card,
        context=context or default_context(config),
        target=forum,
    )
    return report.delivered


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="investment_agent.notifications.earnings_report.run",
        description="최근 공시의 정밀 카드를 원장에 맡겨 한 번만 알린다.",
    ).parse_args(argv)
    configure_logging()
    run()
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
