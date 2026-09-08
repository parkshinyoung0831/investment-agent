"""yfinance의 상대 예상 구간을 회계기간으로 표준화한다."""
from __future__ import annotations

import calendar as month_calendar
from datetime import date, datetime, time
from typing import Any

from investment_agent.platform.logging import get_logger

from investment_agent.data.fundamentals.domain.services.classify_report_session import (
    ET,
    UNKNOWN,
    classify_session,
)

log = get_logger(__name__)

QUARTERS = ("Q1", "Q2", "Q3", "Q4")
_MAX_MATCH_DAYS = 45
_MAX_REPORT_LAG_DAYS = 180


def _coherent_range(prefix: str, low: Any, high: Any) -> dict[str, Any]:
    """추정 구간이 말이 될 때만 싣는다.

    yfinance가 `low > high`인 구간을 주는 일이 있다(실측: eps_low 1.24 > eps_high
    1.15). 저장소는 `estimates_range_check`로 그것을 거절하는데, upsert가 묶음으로
    가므로 **그 한 행이 그 종목 묶음 전체를 실패시킨다.**

    구간만 버리고 평균은 남긴다. 평균은 여전히 쓸 수 있는 값이고, 뒤집힌 구간은
    어느 쪽이 맞는지 알 수 없어 고쳐 쓸 근거가 없다 — 조용히 뒤집어 담으면
    "애널리스트 전망 범위"가 우리가 지어낸 값이 된다.
    """
    try:
        if low is not None and high is not None and float(low) > float(high):
            log.warning(
                "consensus range is inverted; keeping the average only",
                extra={"field": prefix, "low": low, "high": high},
            )
            return {f"{prefix}_low": None, f"{prefix}_high": None}
    except (TypeError, ValueError):
        return {f"{prefix}_low": None, f"{prefix}_high": None}
    return {f"{prefix}_low": low, f"{prefix}_high": high}


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = month_calendar.monthrange(year, month)[1]
    if day.day == month_calendar.monthrange(day.year, day.month)[1]:
        return date(year, month, last)
    return date(year, month, min(day.day, last))


def _next_period(year: int, period: str) -> tuple[int, str]:
    index = QUARTERS.index(period)
    if index == len(QUARTERS) - 1:
        return year + 1, "Q1"
    return year, QUARTERS[index + 1]


def _previous_period(year: int, period: str) -> tuple[int, str]:
    index = QUARTERS.index(period)
    if index == 0:
        return year - 1, "Q4"
    return year, QUARTERS[index - 1]


def _calendar_by_ticker(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, dict[tuple[int, str], dict]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        period = str(row.get("fiscal_period") or "")
        period_end = _as_date(row.get("period_end"))
        try:
            year = int(row.get("fiscal_year"))
        except (TypeError, ValueError):
            continue
        if not ticker or period not in QUARTERS or period_end is None:
            continue
        grouped.setdefault(ticker, {})[(year, period)] = {
            "ticker": ticker,
            "fiscal_year": year,
            "fiscal_period": period,
            "period_end": period_end,
        }

    out: dict[str, list[dict]] = {}
    for ticker, periods in grouped.items():
        known = sorted(periods.values(), key=lambda item: item["period_end"])
        if not known:
            continue
        all_periods = {(row["fiscal_year"], row["fiscal_period"]): row for row in known}
        earliest = known[0]
        year = earliest["fiscal_year"]
        period = earliest["fiscal_period"]
        period_end = earliest["period_end"]
        for _ in range(12):
            year, period = _previous_period(year, period)
            period_end = _add_months(period_end, -3)
            all_periods.setdefault((year, period), {
                "ticker": ticker,
                "fiscal_year": year,
                "fiscal_period": period,
                "period_end": period_end,
            })

        latest = known[-1]
        year = latest["fiscal_year"]
        period = latest["fiscal_period"]
        period_end = latest["period_end"]
        for _ in range(12):
            year, period = _next_period(year, period)
            period_end = _add_months(period_end, 3)
            all_periods.setdefault((year, period), {
                "ticker": ticker,
                "fiscal_year": year,
                "fiscal_period": period,
                "period_end": period_end,
            })
        out[ticker] = sorted(all_periods.values(), key=lambda item: item["period_end"])
    return out


def _latest_reported_quarters(rows: list[dict]) -> dict[str, tuple[int, str]]:
    """DB에 실제 적재된 마지막 분기 키를 미래 투영 행과 구분해 보존한다."""
    latest: dict[str, tuple[date, int, str]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        period = str(row.get("fiscal_period") or "")
        period_end = _as_date(row.get("period_end"))
        try:
            year = int(row.get("fiscal_year"))
        except (TypeError, ValueError):
            continue
        if not ticker or period not in QUARTERS or period_end is None:
            continue
        current = latest.get(ticker)
        if current is None or period_end > current[0]:
            latest[ticker] = (period_end, year, period)
    return {ticker: (row[1], row[2]) for ticker, row in latest.items()}


def _relative_quarter(
    periods: list[dict],
    latest: tuple[int, str] | None,
    offset: int,
) -> dict | None:
    if latest is None:
        return None
    year, period = latest
    for _ in range(offset + 1):
        year, period = _next_period(year, period)
    return next(
        (
            row
            for row in periods
            if row["fiscal_year"] == year and row["fiscal_period"] == period
        ),
        None,
    )


def _nearest_period(periods: list[dict], target: date) -> dict | None:
    if not periods:
        return None
    candidate = min(periods, key=lambda row: abs((row["period_end"] - target).days))
    return candidate if abs((candidate["period_end"] - target).days) <= _MAX_MATCH_DAYS else None


def _annual_period(periods: list[dict], on: date, offset: int) -> dict | None:
    annuals = [
        row for row in periods
        if row["fiscal_period"] == "Q4" and row["period_end"] >= on
    ]
    return annuals[offset] if len(annuals) > offset else None


def _as_datetime(value: object) -> datetime | None:
    """ISO 문자열이나 datetime을 datetime으로 되돌린다(시각 없으면 None)."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def normalize_consensus(
    rows: list[dict],
    fiscal_calendar_rows: list[dict],
    *,
    collected_on: date,
) -> tuple[list[dict], list[dict], list[dict]]:
    """상대 horizon 행을 컨센서스·발표일 행으로 나누고 매핑 실패를 돌려준다."""
    calendars = _calendar_by_ticker(fiscal_calendar_rows)
    latest_reported = _latest_reported_quarters(fiscal_calendar_rows)
    consensus: list[dict] = []
    schedules: list[dict] = []
    unmapped: list[dict] = []

    for row in rows:
        ticker = str(row.get("ticker") or "")
        horizon = str(row.get("horizon") or "")
        periods = calendars.get(ticker, [])
        target = _as_date(row.get("target_period_end"))
        mapping_on = _as_date(row.get("mapping_date")) or collected_on
        kind = "reconstructed" if row.get("source") == "yfinance:eps_trend" else "observed"

        mapped: dict | None
        if horizon in ("q+0", "q+1"):
            mapped = _nearest_period(periods, target) if target else _relative_quarter(
                periods,
                latest_reported.get(ticker),
                0 if horizon == "q+0" else 1,
            )
        elif horizon == "fy+0":
            mapped = _annual_period(periods, mapping_on, 0)
        elif horizon == "fy+1":
            mapped = _annual_period(periods, mapping_on, 1)
        else:
            mapped = None

        snapshot_date = _as_date(row.get("snapshot_date"))
        if not ticker or mapped is None or snapshot_date is None:
            unmapped.append({
                "ticker": ticker or None,
                "horizon": horizon or None,
                "snapshot_date": str(row.get("snapshot_date") or "") or None,
                "reason": "fiscal_period_unmapped",
            })
            continue

        normalized = {
            "ticker": ticker,
            "target_fiscal_year": mapped["fiscal_year"],
            "target_fiscal_period": "FY" if horizon.startswith("fy+") else mapped["fiscal_period"],
            "target_period_end": mapped["period_end"].isoformat(),
            "snapshot_date": snapshot_date.isoformat(),
            "snapshot_kind": kind,
            "source": "yfinance",
            "source_horizon": horizon,
            "eps_avg": row.get("eps_avg"),
            **_coherent_range("eps", row.get("eps_low"), row.get("eps_high")),
            "eps_analysts": row.get("eps_analysts"),
            "revenue_avg": row.get("revenue_avg"),
            **_coherent_range("revenue", row.get("revenue_low"), row.get("revenue_high")),
            "revenue_analysts": row.get("revenue_analysts"),
            "revisions_up_7d": row.get("revisions_up_7d"),
            "revisions_up_30d": row.get("revisions_up_30d"),
            "revisions_down_7d": row.get("revisions_down_7d"),
            "revisions_down_30d": row.get("revisions_down_30d"),
        }
        if normalized["eps_avg"] is not None or normalized["revenue_avg"] is not None:
            consensus.append(normalized)

        expected = _as_date(row.get("expected_report_date"))
        report_lag = (expected - mapped["period_end"]).days if expected else None
        if (
            horizon == "q+0"
            and kind == "observed"
            and report_lag is not None
            and 0 < report_lag <= _MAX_REPORT_LAG_DAYS
        ):
            # 저장하는 사실은 시각 하나다. 발표일은 DB가 ET 기준으로 파생한다.
            # 시각을 못 얻었으면 그 날짜의 ET 자정으로 앵커하되 세션은 unknown으로
            # 남긴다 — 자정을 그대로 분류하면 장전으로 넘겨짚게 된다.
            expected_at = _as_datetime(row.get("expected_report_at"))
            session = row.get("expected_session")
            if expected_at is None:
                expected_at = datetime.combine(expected, time(0, 0), tzinfo=ET)
                session = UNKNOWN
            schedules.append({
                "ticker": ticker,
                "target_fiscal_year": mapped["fiscal_year"],
                "target_fiscal_period": mapped["fiscal_period"],
                "target_period_end": mapped["period_end"].isoformat(),
                "snapshot_date": snapshot_date.isoformat(),
                "expected_report_at": expected_at.isoformat(),
                "expected_session": session or classify_session(expected_at),
                "is_estimated": row.get("is_estimated"),
                "source": "yfinance",
            })
    return consensus, schedules, unmapped

