"""거래일 단위 시세와 corporate action.

**관측한 것만 담는다.** 조정가·수익률처럼 계산으로 나오는 값은 저장하지 않고
`adjustments`가 읽는 시점에 만든다 — 규칙이 바뀔 때 과거 행이 조용히 옛 규칙을
말하는 것을 막기 위해서다.
"""
from __future__ import annotations

DAILY_ROLLING_DAYS = 7
BACKFILL_YEARS = 10
# S&P 500 구성종목이 아니지만 시세를 들고 있어야 하는 벤치마크들. 자산배분 전략이
# 읽는 자산군·섹터 ETF가 여기 있다 — SEC의 company_tickers에는 이 티커들이 없어서
# universe의 상장 동기화로는 들어오지 않고, 빠지면 전략 계산이 "market has unknown
# strategy securities"로 멈춘다.
REFERENCE_PRICE_TICKERS = (
    "SPY", "DBC",
    "AGG", "BIL", "IEF", "TIP", "TLT",
    "EEM", "EFA", "IWM", "SCZ", "VNQ",
    "XLB", "XLC", "XLE", "XLF", "XLI",
    "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
)
SPLIT_REPAIR_GRACE_DAYS = 10

__all__ = [
    "BACKFILL_YEARS",
    "DAILY_ROLLING_DAYS",
    "REFERENCE_PRICE_TICKERS",
    "SPLIT_REPAIR_GRACE_DAYS",
]
