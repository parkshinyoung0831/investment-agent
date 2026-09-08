"""거래일 단위 시세와 corporate action.

**관측한 것만 담는다.** 조정가·수익률처럼 계산으로 나오는 값은 저장하지 않고
`adjustments`가 읽는 시점에 만든다 — 규칙이 바뀔 때 과거 행이 조용히 옛 규칙을
말하는 것을 막기 위해서다.
"""
from __future__ import annotations

DAILY_ROLLING_DAYS = 7
BACKFILL_YEARS = 10
REFERENCE_PRICE_TICKERS = ("SPY",)
SPLIT_REPAIR_GRACE_DAYS = 10

__all__ = [
    "BACKFILL_YEARS",
    "DAILY_ROLLING_DAYS",
    "REFERENCE_PRICE_TICKERS",
    "SPLIT_REPAIR_GRACE_DAYS",
]
