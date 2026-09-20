"""8-K 실적 속보 — 공시 하나를 그 종목의 실적 스레드에 한 번 알린다."""
from __future__ import annotations

import argparse
from collections.abc import Sequence

from investment_agent.config import load_config
from investment_agent.notifications.channels import routing
from investment_agent.notifications.channels.contracts import ForumThread
from investment_agent.notifications.context import default_context
from investment_agent.notifications.earnings_flash.candidates import load_flash_candidates
from investment_agent.notifications.earnings_flash.embeds import build_flash_embed
from investment_agent.notifications.engine import (
    Notice,
    PublishContext,
    Rendered,
    fact_time,
    publish,
)
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.notifications.topics import topic
from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.reporting.notifications.earnings_flash import EarningsFlashStore

log = get_logger(__name__)

TOPIC = topic("earnings.flash")


def notices(items: Sequence[dict]) -> list[Notice]:
    """정체성은 (종목, accession_no)다. 같은 8-K는 몇 번을 읽어도 한 번만 알린다."""
    out = []
    for item in items:
        flash = item["flash"]
        out.append(Notice(
            subject=str(flash["ticker"]),
            occurrence=str(flash["accession_no"]),
            fact_at=fact_time(flash.get("available_at") or flash["filed_at"]),
            basis={
                "revenue_actual": flash.get("revenue_actual"),
                "eps_actual": flash.get("eps_actual"),
            },
            data=item,
        ))
    return out


def render(batch: list[Notice]) -> Rendered:
    notice, = batch
    names = notice.data.get("names") or {}
    name = str(names.get("name_ko") or names.get("name") or notice.subject)
    return Rendered(
        {"content": f"⚡ **{notice.subject}** 실적 발표 속보가 접수되었습니다.",
         "embeds": [build_flash_embed(notice.data)]},
        # 속보와 정밀 분석이 같은 종목 스레드에 쌓여야 "그 종목에 무슨 일이 있었나"를 한 줄기로 읽는다.
        thread=ForumThread(notice.subject, routing.ticker_thread_title(notice.subject, name)),
    )


def run(*, tickers: set[str] | None = None, store: EarningsFlashStore | None = None,
        target: str | None = None, context: PublishContext | None = None) -> int:
    config = load_config()
    store = store or EarningsFlashStore.configured(config)
    candidates = notices(load_flash_candidates(store, tickers))
    if not candidates:
        log.info("flash: 최근 8-K 실적 속보 없음")
        return 0
    report = publish(
        TOPIC, candidates, render,
        context=context or default_context(config),
        target=discord_target(TOPIC.channel_kind, config=config, override=target),
    )
    return report.delivered


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="investment_agent.notifications.earnings_flash.run",
        description="8-K 실적 속보를 원장에 맡겨 한 번만 알린다.",
    ).parse_args(argv)
    configure_logging()
    run()
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
