"""기술지표 저장 이력을 730일로 제한한다."""
from __future__ import annotations

from datetime import date, timedelta

from investment_agent.platform.clock import us_market_today
from investment_agent.platform.logging import get_logger
from investment_agent.research.features import STORAGE_DAYS, db

log = get_logger(__name__)

RETENTION_DAYS = STORAGE_DAYS


def prune_history(*, today: date | None = None) -> int:
    """730일보다 오래된 저장형 RSI·MACD 행을 제거한다."""
    cutoff = ((today or us_market_today()) - timedelta(days=RETENTION_DAYS)).isoformat()
    deleted = db.delete_before(cutoff)
    log.info("tech indicators retention cutoff=%s deleted=%d", cutoff, deleted)
    return deleted
