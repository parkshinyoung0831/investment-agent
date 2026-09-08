"""13F 공시 이력을 5년(20분기)으로 제한한다.

13F는 분기 종료 후 최대 45일 지연 공개라 장기 보관의 신호 가치가 낮다.
``institutional.positions``는 ``filings``를 ON DELETE CASCADE로 참조하므로
``filings``만 지워도 보유내역이 함께 정리된다.
"""
from __future__ import annotations

from datetime import date

from datetime import datetime
from zoneinfo import ZoneInfo

from investment_agent.platform.logging import get_logger
from investment_agent.data.institutional import persistence as db

log = get_logger(__name__)

RETENTION_YEARS = 5


def _years_ago(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def prune_history(*, today: date | None = None) -> int:
    """5년보다 오래된 13F 공시(및 연쇄 삭제되는 보유내역)를 제거한다."""
    anchor = today or datetime.now(ZoneInfo("America/New_York")).date()
    cutoff = _years_ago(anchor, RETENTION_YEARS).isoformat()
    deleted = db.delete_filings_before(cutoff)
    log.info("institutional retention cutoff=%s deleted=%d", cutoff, deleted)
    return deleted
