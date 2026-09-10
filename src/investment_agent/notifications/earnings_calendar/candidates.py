"""이번 주 실적 캘린더 후보를 고르는 entry-side reader."""
from __future__ import annotations

import os
from datetime import date

from investment_agent.reporting.notifications.earnings_calendar import EarningsCalendarStore
from investment_agent.platform.logging import get_logger
from investment_agent.reporting.services.earnings import schedule as metrics

log = get_logger(__name__)


def force_resend() -> bool:
    return os.environ.get("FUNDAMENTALS_CALENDAR_FORCE", "").lower() in ("1", "on", "true")


def _default_store() -> EarningsCalendarStore:
    return EarningsCalendarStore.configured()


def collect(store: EarningsCalendarStore, today: date | None = None) -> tuple[list[dict], date | None, str]:
    today = today or date.today()
    tickers = [str(member["ticker"]) for member in store.watchlist_members()]
    week = metrics.iso_week(today)
    if not tickers:
        log.info("calendar: 활성 관심종목 없음 — 조회 생략")
        return [], None, week
    snapshots = store.schedule_snapshots(tickers)
    rows = metrics.build_rows(snapshots, store.prior_filings(tickers), store.load_names(tickers), today)
    snapshot_dates = [
        parsed for parsed in (metrics.as_date(row.get("snapshot_date")) for row in snapshots) if parsed
    ]
    return rows, (max(snapshot_dates) if snapshot_dates else None), week


def schedule_notification_key(row: dict) -> str | None:
    """종목별 예정 안내의 안정적인 outbox 키를 만든다.

    예정일이 바뀌면 새 키가 되어 다시 알리고, 같은 예정은 주간 요약과 독립적으로
    한 번만 보낸다. preflight와 dispatcher가 반드시 같은 키를 써야 한다.
    """
    ticker = str(row.get("ticker") or "")
    expected = row.get("expected")
    if not ticker or expected is None:
        return None
    return (f"schedule:{ticker}:{row.get('target_fiscal_year')}:"
            f"{row.get('target_fiscal_period')}:{expected}")


def pending_state(
    today: date | None = None, *, store: EarningsCalendarStore | None = None,
) -> dict[str, int | bool | str]:
    store = store or _default_store()
    rows, _, week = collect(store, today)
    already_sent = bool(rows) and not force_resend() and week in store.sent_weeks()
    sent_schedules = store.sent_schedule_keys()
    schedule_updates = sum(
        key is not None and key not in sent_schedules
        for key in (schedule_notification_key(row) for row in rows)
    )
    return {
        "iso_week": week,
        "upcoming_releases": len(rows),
        "schedule_updates": schedule_updates,
        "should_notify": bool(rows) and (not already_sent or bool(schedule_updates)),
    }


__all__ = ["collect", "force_resend", "pending_state", "schedule_notification_key"]
