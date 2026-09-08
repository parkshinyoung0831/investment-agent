"""Market history retention policy.

Supabase에는 연속된 일봉만 남기고, 전체 Yahoo 일봉은 Parquet archive가 보관한다.
서로 다른 해상도의 행을 같은 canonical 가격 표에 섞지 않는다.
"""
from __future__ import annotations

from datetime import date

from investment_agent.platform.clock import us_market_today
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

def _years_ago(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def compact_price_rows(
    rows: list[dict],
    *,
    today: date | None = None,
) -> list[dict]:
    """Supabase 보관 범위 안의 연속 일봉만 남긴다."""
    anchor = today or us_market_today()
    daily_cutoff = _years_ago(anchor, 7)
    kept: dict[tuple[str, str], dict] = {}

    for row in rows:
        trade_date = date.fromisoformat(str(row["trade_date"]))
        ticker = str(row["ticker"])
        key = (ticker, trade_date.isoformat())
        if trade_date >= daily_cutoff:
            kept[key] = row
    return [kept[key] for key in sorted(kept)]


def prune_history(*, today: date | None = None) -> dict[str, int]:
    """v1 market 계약은 append-only 관측 원장만 정의하므로 삭제하지 않는다."""
    del today
    result = {"prices_deleted": 0}
    log.info("market retention is disabled by append-only policy (%s)", result)
    return result
