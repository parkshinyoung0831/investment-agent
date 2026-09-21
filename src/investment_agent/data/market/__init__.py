"""거래일 단위 시세와 corporate action.

**관측한 것만 담는다.** 조정가·수익률처럼 계산으로 나오는 값은 저장하지 않고 읽는 쪽이
필요할 때 만든다 — 규칙이 바뀔 때 과거 행이 조용히 옛 규칙을 말하는 것을 막기 위해서다.
"""
from __future__ import annotations

# 목록은 universe가 소유한다 — 그 종목들의 security_id를 만드는 곳이 universe이고,
# universe는 다른 파이프라인을 import하지 않는다.
from investment_agent.data.universe import REFERENCE_PRICE_TICKERS

DAILY_ROLLING_DAYS = 7
BACKFILL_YEARS = 10
SPLIT_REPAIR_GRACE_DAYS = 10

__all__ = [
    "BACKFILL_YEARS",
    "DAILY_ROLLING_DAYS",
    "REFERENCE_PRICE_TICKERS",
    "SPLIT_REPAIR_GRACE_DAYS",
]
