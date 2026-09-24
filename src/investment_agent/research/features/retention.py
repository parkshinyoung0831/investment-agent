"""기술지표 저장 이력의 하한.

지표는 로컬 Research 저장소에만 있고 행이 작다(12년 × 600종목이 수십 MB). 과거 재현·ML 학습이
2015년부터의 지표를 읽으므로 그보다 오래된 행만 지운다. Supabase 가격으로 다시 계산하는 창
(`RETENTION_DAYS`, backfill·daily)은 그대로 2년이다 — 그 앞은 `long_history`가 로컬 긴 가격 이력으로 채운다.
"""
from __future__ import annotations

from datetime import date

from investment_agent.platform.logging import get_logger
from investment_agent.research.features import STORAGE_DAYS, db

log = get_logger(__name__)

# Supabase 가격으로 다시 계산하는 창. 저장 하한이 아니다.
RETENTION_DAYS = STORAGE_DAYS
# 저장 하한. S&P 500 시점 멤버십 이력(2015-03)과 재현 시작에 맞춘다.
HISTORY_FLOOR = date(2015, 1, 1)


def prune_history(*, today: date | None = None) -> int:
    """저장 하한보다 오래된 RSI·MACD 행을 제거한다. `today`는 호출 계약을 유지하려고 받는다."""
    cutoff = HISTORY_FLOOR.isoformat()
    deleted = db.delete_before(cutoff)
    log.info("tech indicators retention cutoff=%s deleted=%d", cutoff, deleted)
    return deleted
