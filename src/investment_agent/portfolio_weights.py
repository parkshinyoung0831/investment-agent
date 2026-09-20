"""Research 시뮬레이션과 Trading 판단이 공유하는 long-only 비중 벡터 계약."""
from __future__ import annotations

import math
import re
from typing import Any, Mapping

from investment_agent.platform.serialization import ContractError

# 현금은 종목이 아니라 비중 벡터의 나머지 칸이다. 종목 티커로는 쓸 수 없다.
CASH_SYMBOL = "CASH"
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


def validated_weights(weights: Mapping[str, Any], *, require_total: bool = True) -> dict[str, float]:
    """long-only 비중을 검증하고 현금 항목을 포함한 정렬 사본을 반환한다."""
    if not isinstance(weights, Mapping) or not weights:
        raise ContractError("weights must be a non-empty mapping")
    parsed: dict[str, float] = {}
    for raw_symbol, raw_weight in weights.items():
        symbol = str(raw_symbol).upper().strip()
        if symbol != CASH_SYMBOL and not TICKER_RE.fullmatch(symbol):
            raise ContractError(f"invalid portfolio symbol: {symbol}")
        if symbol in parsed:
            raise ContractError(f"duplicate portfolio symbol: {symbol}")
        if isinstance(raw_weight, bool) or not isinstance(raw_weight, (int, float)):
            raise ContractError(f"weight for {symbol} must be numeric")
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight < 0.0 or weight > 1.0:
            raise ContractError(f"weight for {symbol} must be between 0 and 1")
        parsed[symbol] = weight
    parsed.setdefault(CASH_SYMBOL, 0.0)
    total = math.fsum(parsed.values())
    if require_total and not math.isclose(total, 1.0, abs_tol=1e-8):
        raise ContractError(f"weights including CASH must sum to 1, got {total:.12f}")
    return {symbol: parsed[symbol] for symbol in sorted(parsed)}


__all__ = ["CASH_SYMBOL", "TICKER_RE", "validated_weights"]
