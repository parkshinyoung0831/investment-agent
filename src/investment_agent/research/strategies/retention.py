"""전략 배분 이력을 3년으로 제한한다."""
from __future__ import annotations

from datetime import date

from investment_agent.platform.clock import us_market_today
from investment_agent.platform.logging import get_logger
from investment_agent.research.strategies import db

log = get_logger(__name__)

RETENTION_YEARS = 3


def _years_ago(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def prune_history(*, today: date | None = None) -> int:
    """3년보다 오래된 전략 배분을 제거한다."""
    anchor = today or us_market_today()
    cutoff = _years_ago(anchor, RETENTION_YEARS).isoformat()
    deleted = db.delete_allocations_before(cutoff)
    log.info("strategy retention cutoff=%s deleted=%d", cutoff, deleted)
    return deleted
