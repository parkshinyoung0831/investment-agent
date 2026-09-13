"""이번 주 실적 캘린더 후보를 고르는 entry-side reader."""
from __future__ import annotations

from datetime import date, timedelta

from investment_agent.notifications.engine import Notice, fact_time, unsettled
from investment_agent.notifications.topics import topic
from investment_agent.reporting.notifications.earnings_calendar import EarningsCalendarStore
from investment_agent.platform.logging import get_logger
from investment_agent.reporting.services.earnings import schedule as metrics

log = get_logger(__name__)


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


WEEK_TOPIC = topic("earnings.week")
SCHEDULE_TOPIC = topic("earnings.schedule")
WATCHLIST = "watchlist"


def week_notice(rows: list[dict], today: date, week: str, snapshot_date: date | None) -> Notice:
    """주 1장. 내용은 카드에 찍히는 종목·예정일·서식·신뢰도다 — 바뀌면 그 주 카드를 고친다."""
    monday = today - timedelta(days=today.weekday())
    return Notice(
        subject=WATCHLIST,
        occurrence=week,
        fact_at=fact_time(monday.isoformat()),
        basis={"rows": sorted(
            [str(r.get("ticker")), str(r.get("expected")), str(r.get("form_expected")), str(r.get("confidence"))]
            for r in rows
        )},
        data={"rows": rows, "today": today, "snapshot_date": snapshot_date, "week": week},
    )


def schedule_notices(rows: list[dict], today: date) -> list[Notice]:
    """종목·분기마다 "다음 발표 예정". 사람이 아는 예정일과 달라졌을 때만 그 종목 스레드에 남는다."""
    out = []
    for row in rows:
        ticker = str(row.get("ticker") or "")
        expected = row.get("expected")
        if not ticker or expected is None:
            continue
        out.append(Notice(
            subject=f"{ticker}:{row.get('target_fiscal_year')}-{row.get('target_fiscal_period')}",
            occurrence=today.isoformat(),
            fact_at=fact_time(today.isoformat()),
            basis={"expected": str(expected)},
            data=row,
        ))
    return out


def pending_state(
    ledger, today: date | None = None, *, store: EarningsCalendarStore | None = None,
) -> dict[str, int | bool | str]:
    """렌더 의존성 설치 전 사전 점검. 원장이 아직 보내지 않은 주간 카드·예정 안내를 센다."""
    store = store or _default_store()
    today = today or date.today()
    rows, snapshot_date, week = collect(store, today)
    week_pending = bool(rows) and bool(
        unsettled(WEEK_TOPIC, [week_notice(rows, today, week, snapshot_date)], ledger=ledger)
    )
    schedule_updates = len(unsettled(SCHEDULE_TOPIC, schedule_notices(rows, today), ledger=ledger))
    return {
        "iso_week": week,
        "upcoming_releases": len(rows),
        "schedule_updates": schedule_updates,
        "should_notify": week_pending or bool(schedule_updates),
    }


__all__ = ["SCHEDULE_TOPIC", "WEEK_TOPIC", "collect", "pending_state", "schedule_notices", "week_notice"]
