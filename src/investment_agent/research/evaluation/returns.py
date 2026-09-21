"""Research 평가에 쓰는 배당·분할 포함 가격 경로 수익률."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from investment_agent.platform.serialization import finite_float


def total_return(rows_asc: list[Mapping[str, Any]], end_index: int) -> float:
    """시작 종가 이후 배당을 포함한 단순 총수익률을 계산한다.

    `market.prices_daily.close`와 `market.actions_daily.dividend_amount`는 둘 다
    **수집 시점의 분할 기준으로 과거까지 back-adjust된** 값이다(yfinance
    `auto_adjust=False`는 분할만 조정한다). 그래서 여기서 분할 비율로 보유 주식수를
    늘리면 분할이 든 구간의 수익률이 분할 배수만큼 부풀려진다 — 10:1 분할 구간이
    가격이 그대로여도 +900%가 된다. 분할 비율은 **값 검증에만** 쓰고 수익률에는
    반영하지 않는다. 같은 규약이 `research/features/layer.py`와
    `research/valuation/inputs.py`에도 적혀 있다.
    """
    if not rows_asc or end_index >= len(rows_asc) or end_index < 1:
        raise ValueError("insufficient price path")
    start = finite_float(rows_asc[0].get("close"))
    end = finite_float(rows_asc[end_index].get("close"))
    if start is None or end is None or start <= 0:
        raise ValueError("invalid close in price path")
    dividends = 0.0
    for row in rows_asc[1:end_index + 1]:
        ratio = finite_float(row.get("split_ratio"))
        if ratio is not None and ratio <= 0:
            raise ValueError("invalid split ratio in price path")
        dividends += finite_float(row.get("div_amount")) or 0.0
    return (end + dividends) / start - 1
