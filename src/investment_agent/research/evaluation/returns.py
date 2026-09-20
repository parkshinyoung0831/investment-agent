"""Research 평가에 쓰는 배당·분할 포함 가격 경로 수익률."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from investment_agent.platform.serialization import finite_float


def total_return(rows_asc: list[Mapping[str, Any]], end_index: int) -> float:
    """시작 종가 이후 배당을 포함한 단순 총수익률을 계산한다."""
    if not rows_asc or end_index >= len(rows_asc) or end_index < 1:
        raise ValueError("insufficient price path")
    start = finite_float(rows_asc[0].get("close"))
    end = finite_float(rows_asc[end_index].get("close"))
    if start is None or end is None or start <= 0:
        raise ValueError("invalid close in price path")
    shares = 1.0
    dividends = 0.0
    for row in rows_asc[1:end_index + 1]:
        ratio = finite_float(row.get("split_ratio"))
        if ratio is not None:
            if ratio <= 0:
                raise ValueError("invalid split ratio in price path")
            shares *= ratio
        dividends += shares * (finite_float(row.get("div_amount")) or 0.0)
    return (end * shares + dividends) / start - 1
