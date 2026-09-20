"""v1 주간 실적 캘린더 알림 진입점."""
from __future__ import annotations

import asyncio
import argparse
from collections.abc import Sequence
from datetime import date

from investment_agent.config import load_config
from investment_agent.notifications.channels import routing
from investment_agent.notifications.channels.contracts import ForumThread
from investment_agent.notifications.context import default_context
from investment_agent.notifications.earnings_calendar import card
from investment_agent.notifications.earnings_calendar.candidates import (
    SCHEDULE_TOPIC, WEEK_TOPIC, collect, schedule_notices, week_notice,
)
from investment_agent.notifications.earnings_calendar.render import render, shoot_png
from investment_agent.notifications.engine import PublishContext, Rendered, publish
from investment_agent.notifications.playwright import persist_png
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.platform.clock import kst_today
from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.reporting.notifications.earnings_calendar import EarningsCalendarStore

log = get_logger(__name__)


def _schedule_embed(row: dict) -> dict:
    """종목 스레드에 남길 '다음 발표 예정' 한 장.

    확정이 아니다 — 출처가 확정 여부를 알려주지 않는다. 등급(estimated/shifted/
    stale)을 숨기지 않고 그대로 적는다.
    """
    grade = {
        "estimated": "추정",
        "shifted": "변경됨",
        "stale": "스냅샷 오래됨",
    }.get(str(row.get("confidence")), str(row.get("confidence") or ""))
    fields = [
        {"name": "예상 발표일", "value": str(row.get("expected") or "-"), "inline": True},
        {"name": "대상 분기", "value": f"{row.get('target_fiscal_year') or '-'} "
                                   f"{row.get('target_fiscal_period') or '-'}", "inline": True},
        {"name": "예상 서식", "value": str(row.get("form_expected") or "-"), "inline": True},
        {"name": "신뢰도", "value": grade, "inline": True},
    ]
    if row.get("previous_expected"):
        fields.append({"name": "이전 예정일", "value": str(row["previous_expected"]), "inline": True})
    if row.get("prior_filed_at"):
        fields.append({
            "name": "작년 같은 분기 제출", "value": str(row["prior_filed_at"]), "inline": True,
        })
    return {
        "title": f"다음 실적 발표 예정 · D-{row.get('days_until')}",
        "description": f"{row.get('name')} ({row.get('ticker')})",
        "fields": fields,
    }


def _schedule_tags(target: str, config) -> tuple[str, ...]:
    """예정 안내는 '발표예정' 태그 하나만 단다 — 결과와 갈라 읽기 위해서다."""
    try:
        from investment_agent.notifications.channels.directory import guild_directory

        return tuple(guild_directory(config).tag_ids_by_channel_id(target, ("발표예정",)))
    except Exception:  # noqa: BLE001 - 태그 실패가 발송을 막지 않는다
        return ()


def run(*, store: EarningsCalendarStore | None = None, target: str | None = None,
        context: PublishContext | None = None, today: date | None = None) -> int:
    """주간 캘린더 카드와 종목별 다음 발표 예정을 원장에 맡긴다.

    주간 카드는 "이번 주에 무엇이 있나"를 한 장으로 본다. 반면 한 종목을 파는 사람은 그
    종목 스레드만 연다 — 거기에 예정이 없으면 속보가 아무 예고 없이 떨어진다. 같은 사실을
    두 곳에 쓰는 것이 아니라, 읽는 방향이 둘이다.
    """
    config = load_config()
    store = store or EarningsCalendarStore.configured(config)
    today = today or kst_today()
    rows, snapshot_date, week = collect(store, today)
    if not rows:
        log.info("calendar: %s 주에 발표 예정 종목 없음 - 종료", week)
        return 0
    context = context or default_context(config)

    def render_week(batch):
        notice, = batch
        data = notice.data
        ctx, caption = card.build(data["rows"], data["today"], data["snapshot_date"])
        png = persist_png(
            asyncio.run(shoot_png(render("calendar.html.j2", ctx))), kind="earnings_calendar", name=data["week"],
        )
        return Rendered({"content": caption}, attachment_path=png)

    delivered = publish(
        WEEK_TOPIC, [week_notice(rows, today, week, snapshot_date)], render_week,
        context=context, target=discord_target(WEEK_TOPIC.channel_kind, config=config, override=target),
    ).delivered

    try:
        forum = discord_target(SCHEDULE_TOPIC.channel_kind, config=config)
    except Exception:  # noqa: BLE001 - 예정 안내 실패가 주간 카드를 막지 않는다
        log.warning("calendar: 실적 포럼 목적지를 찾지 못해 종목별 예정 안내를 건너뛴다")
        return delivered
    tags = _schedule_tags(forum, config)

    def render_schedule(batch):
        notice, = batch
        row = notice.data
        ticker = str(row["ticker"])
        return Rendered(
            {"embeds": [_schedule_embed(row)]},
            thread=ForumThread(ticker, routing.ticker_thread_title(ticker, str(row.get("name") or ticker)), tags),
        )

    delivered += publish(
        SCHEDULE_TOPIC, schedule_notices(rows, today), render_schedule, context=context, target=forum,
    ).delivered
    return delivered


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="investment_agent.notifications.earnings_calendar.run",
        description="주간 실적 캘린더와 종목별 발표 예정을 원장에 맡겨 한 번만 알린다.",
    ).parse_args(argv)
    configure_logging()
    try:
        run()
    except Exception:
        log.exception("earnings calendar notification failed")
        return 1
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
