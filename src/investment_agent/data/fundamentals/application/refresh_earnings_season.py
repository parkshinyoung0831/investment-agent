"""발표 예정일을 기준으로 관심종목 fast path 실행 여부를 판정한다."""
from __future__ import annotations

import os
from datetime import date, timedelta

from investment_agent.platform.clock import us_market_today
from investment_agent.data.fundamentals.application import CompanyFinancialRepository

_DEFAULT_LEAD_DAYS = 5
_DEFAULT_LAG_DAYS = 10
_DEFAULT_STALE_DAYS = 7


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def lead_days() -> int:
    """실적 예정일 전에 fast path를 시작할 일수."""
    return _env_int("FUNDAMENTALS_FAST_LEAD_DAYS", _DEFAULT_LEAD_DAYS)


def lag_days() -> int:
    """실적 예정일 뒤에도 fast path를 유지할 일수."""
    return _env_int("FUNDAMENTALS_FAST_LAG_DAYS", _DEFAULT_LAG_DAYS)


def stale_days() -> int:
    """발표 일정 스냅샷을 신뢰할 최대 경과 일수."""
    return _env_int("FUNDAMENTALS_FAST_STALE_DAYS", _DEFAULT_STALE_DAYS)


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def evaluate_earnings_season(
    rows: list[dict],
    today: date,
    *,
    lead: int | None = None,
    lag: int | None = None,
    stale: int | None = None,
) -> dict:
    """예정일 관측값을 fail-open 시즌 상태로 변환한다."""
    lead = lead_days() if lead is None else lead
    lag = lag_days() if lag is None else lag
    stale = stale_days() if stale is None else stale

    if not rows:
        return {"in_season": True, "reason": "no_snapshot", "tickers": [], "window": []}
    snapshots = [day for day in (_as_date(row.get("snapshot_date")) for row in rows) if day]
    if not snapshots or (today - max(snapshots)).days > stale:
        return {"in_season": True, "reason": "stale_snapshot", "tickers": [], "window": []}
    dated = [
        (str(row.get("ticker") or ""), _as_date(row.get("expected_report_date")))
        for row in rows
    ]
    dated = [(ticker, day) for ticker, day in dated if day is not None]
    if not dated:
        return {"in_season": True, "reason": "no_expected_dates", "tickers": [], "window": []}
    hits = sorted(
        ticker
        for ticker, day in dated
        if day - timedelta(days=lead) <= today <= day + timedelta(days=lag)
    )
    if hits:
        return {
            "in_season": True,
            "reason": "within_window",
            "tickers": hits,
            "window": [lead, lag],
        }
    return {
        "in_season": False,
        "reason": "out_of_season",
        "tickers": [],
        "window": [lead, lag],
    }


def refresh_earnings_season(
    *,
    repository: CompanyFinancialRepository,
    today: date | None = None,
    lead: int | None = None,
    lag: int | None = None,
    stale: int | None = None,
) -> dict:
    """저장된 관심종목 발표 일정을 읽어 현재 시즌 상태를 반환한다."""
    return evaluate_earnings_season(
        repository.watchlist_expected_reports(),
        today or us_market_today(),
        lead=lead,
        lag=lag,
        stale=stale,
    )


# Actions 진입점이 사용할 단일 평가 함수 별칭이다.
evaluate = evaluate_earnings_season


def github_output_lines(state: dict) -> str:
    """GitHub Actions 출력 파일에 추가할 안정적인 key=value 문자열."""
    return (
        f"in_season={'true' if state['in_season'] else 'false'}\n"
        f"season_reason={state['reason']}\n"
        f"season_tickers={','.join(state['tickers'])}\n"
    )
