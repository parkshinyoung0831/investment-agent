"""v1 주간 실적 캘린더 알림 진입점."""
from __future__ import annotations

import asyncio
import argparse
from collections.abc import Sequence
from datetime import date

from investment_agent.config import load_config
from investment_agent.notifications.earnings_calendar.candidates import collect, force_resend
from investment_agent.notifications.earnings_calendar.render import render, shoot_png
from investment_agent.notifications.playwright import persist_png
from investment_agent.reporting.notifications.earnings_calendar import EarningsCalendarStore
from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.earnings_calendar import card
from investment_agent.notifications.outbox import Outbox
from investment_agent.notifications.service import NotificationService
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.notifications.channels import routing
from investment_agent.platform.clock import utc_now
from investment_agent.platform.logging import configure_logging, get_logger

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


async def _post_schedules(rows: list[dict], *, config, service, today: date) -> int:
    """종목별 다음 발표 예정을 그 종목의 실적 스레드에 남긴다.

    주간 캘린더 카드는 "이번 주에 무엇이 있나"를 한 장으로 본다. 반면 한 종목을
    파는 사람은 그 종목 스레드만 연다 — 거기에 예정이 없으면 속보가 아무 예고
    없이 떨어진다. 같은 사실을 두 곳에 쓰는 것이 아니라, 읽는 방향이 둘이다.
    """
    try:
        target = discord_target("fundamentals_schedule", config=config)
    except Exception:  # noqa: BLE001 - 예정 안내 실패가 주간 카드를 막지 않는다
        log.warning("calendar: 실적 포럼 목적지를 찾지 못해 종목별 예정 안내를 건너뛴다")
        return 0
    posted = 0
    for row in rows:
        ticker = str(row.get("ticker") or "")
        expected = row.get("expected")
        if not ticker or expected is None:
            continue
        # 예정일이 바뀌면 다시 알린다 — 키에 날짜를 넣어 그것을 새 알림으로 만든다.
        key = (f"schedule:{ticker}:{row.get('target_fiscal_year')}:"
               f"{row.get('target_fiscal_period')}:{expected}")
        result = service.enqueue(
            producer="fundamentals",
            notification_key=key,
            kind="fundamentals_schedule",
            target=target,
            message={"embeds": [_schedule_embed(row)]},
            entity_key=ticker,
            period_end=row.get("target_period_end") or today,
            thread_name=routing.ticker_thread_title(ticker, str(row.get("name") or ticker)),
            thread_tags=_schedule_tags(target, config),
        )
        if result.status == "enqueued":
            posted += 1
    return posted


def _schedule_tags(target: str, config) -> tuple[str, ...]:
    """예정 안내는 '발표예정' 태그 하나만 단다 — 결과와 갈라 읽기 위해서다."""
    try:
        from investment_agent.notifications.channels.directory import guild_directory

        return tuple(guild_directory(config).tag_ids_by_channel_id(target, ("발표예정",)))
    except Exception:  # noqa: BLE001 - 태그 실패가 발송을 막지 않는다
        return ()


async def run(*, store: EarningsCalendarStore | None = None,
              service: NotificationService | None = None,
              target: str | None = None) -> int:
    config = load_config()
    if store is None:
        store = EarningsCalendarStore.configured(config)
    today = date.today()
    rows, snapshot_date, week = collect(store, today)
    if not rows:
        log.info("calendar: %s 주에 발표 예정 종목 없음 — 종료", week)
        return 0
    if not force_resend() and week in store.sent_weeks():
        log.info("calendar: %s 주는 이미 outbox에 등록됨 — 종료", week)
        return 0

    target_id = discord_target("fundamentals_calendar", config=config, override=target)
    ctx, caption = card.build(rows, today, snapshot_date)
    png_path = persist_png(
        await shoot_png(render("calendar.html.j2", ctx)),
        kind="earnings_calendar", name=week,
    )
    channel = DiscordChannel(config)
    if service is None:
        service = NotificationService(Outbox(store.database), channel, clock=utc_now)
    key = f"calendar:{week}:force" if force_resend() else f"calendar:{week}"
    result = service.enqueue(
        producer="fundamentals",
        notification_key=key,
        kind="fundamentals_calendar",
        target=target_id,
        message={"content": caption},
        period_end=today,
        attachment_path=png_path,
    )
    # 종목별 예정 안내는 주간 카드와 무관하게 등록한다 — 주간 카드가 이미 나간
    # 주에도 예정일이 바뀌면 그 종목 스레드에는 알려야 한다.
    scheduled = await _post_schedules(rows, config=config, service=service, today=today)
    if result.status == "enqueued" or scheduled:
        service.run_pending()
        log.info("calendar enqueued %s — 종목 %d개 · 종목별 예정 %d건",
                 week, len(rows), scheduled)
    return 0 if result.status in {"enqueued", "duplicate"} else 1


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="investment_agent.notifications.earnings_calendar.run",
        description="관심종목 주간 실적 캘린더 알림을 outbox에 등록한다.",
    ).parse_args(argv)
    configure_logging()
    try:
        return asyncio.run(run())
    except Exception:
        log.exception("earnings calendar notification failed")
        return 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
