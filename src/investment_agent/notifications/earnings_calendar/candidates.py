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


def pending_state(
    today: date | None = None, *, store: EarningsCalendarStore | None = None,
) -> dict[str, int | bool | str]:
    store = store or _default_store()
    rows, _, week = collect(store, today)
    already_sent = bool(rows) and not force_resend() and week in store.sent_weeks()
    return {
        "iso_week": week,
        "upcoming_releases": len(rows),
        "should_notify": bool(rows) and not already_sent,
    }


__all__ = ["collect", "force_resend", "pending_state"]
