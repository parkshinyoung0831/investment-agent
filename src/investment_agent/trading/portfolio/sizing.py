"""승인된 비중을 **실제로 낼 수 있는 수량**으로 바꾼다.

## 비중과 수량 사이에는 현실이 있다

비중 3.7%는 주식 수로 딱 떨어지지 않는다. 그 사이에서 조용히 틀리는 것이 셋 있다.

1. **반올림.** 소수점을 버리면 목표보다 적게 사고, 올리면 현금을 초과한다. 어느
   쪽이든 티가 안 난다.
2. **최소 주문 금액.** 한 주 값보다 작은 목표는 주문이 아예 안 나가는데, 장부에는
   "목표 비중이 있다"고 남는다. 그러면 매일 같은 주문을 다시 시도한다.
3. **잔돈 포지션.** 목표와 현재의 차이가 몇 천 원이면 수수료가 그 차이보다 크다.

여기서 하는 일은 그 셋을 **명시적으로** 처리하고, 처리한 내용을 남기는 것이다.

## 내림을 기본으로 한다

목표를 넘기지 않는 쪽으로 반올림한다. 현금이 모자라 주문이 거부되면 그 종목만 빠지는
것이 아니라 배치 전체가 흔들리기 때문이다. 적게 사는 것은 다음 회차에 채울 수 있다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from investment_agent.platform.serialization import finite_float

# 이보다 작은 비중 차이는 주문하지 않는다. 수수료가 이득보다 크다.
DEFAULT_MIN_TRADE_WEIGHT = 0.002


@dataclass(frozen=True)
class TargetPosition:
    """한 종목의 목표. 수량은 정수다 — 소수점 주식은 다루지 않는다."""

    ticker: str
    target_weight: float
    price: float
    target_quantity: int
    current_quantity: int = 0

    @property
    def delta_quantity(self) -> int:
        """실제로 내야 하는 주문 수량. 양수면 매수, 음수면 매도."""
        return self.target_quantity - self.current_quantity

    @property
    def notional(self) -> float:
        return abs(self.delta_quantity) * self.price


@dataclass(frozen=True)
class SizingResult:
    positions: list[TargetPosition]
    # 왜 그 종목을 건너뛰었는지. 남기지 않으면 "왜 안 샀나"에 답할 수 없다.
    skipped: list[dict[str, Any]]
    # 반올림·최소금액 처리 뒤 실제로 투자되는 비중.
    invested_weight: float

    def orders(self) -> list[TargetPosition]:
        """주문이 실제로 나갈 종목만."""
        return [position for position in self.positions if position.delta_quantity != 0]


def size_portfolio(
    weights: Mapping[str, Any],
    prices: Mapping[str, Any],
    *,
    equity: float,
    current_quantities: Mapping[str, int] | None = None,
    min_trade_weight: float = DEFAULT_MIN_TRADE_WEIGHT,
) -> SizingResult:
    """승인된 비중 → 주문 수량.

    `equity`는 계좌의 총 평가액이다. 현금이 아니라 총액인 이유: 비중은 총액 대비로
    정의되고, 현금 대비로 계산하면 이미 보유한 종목을 다시 사게 된다.
    """
    if equity <= 0:
        raise ValueError("equity must be positive")

    held = dict(current_quantities or {})
    positions: list[TargetPosition] = []
    skipped: list[dict[str, Any]] = []

    for ticker in sorted(set(weights) | set(held)):
        weight = finite_float(weights.get(ticker), 0.0) or 0.0
        price = finite_float(prices.get(ticker))
        current = int(held.get(ticker, 0))

        if price is None or price <= 0:
            # 값을 모르면 수량을 정할 수 없다. 0으로 두면 **전량 매도**가 되므로
            # 절대 그렇게 하지 않는다.
            skipped.append({"ticker": ticker, "reason": "no_price"})
            continue

        # 목표를 넘기지 않도록 내림. 넘치면 현금 부족으로 배치가 흔들린다.
        target_quantity = math.floor(weight * equity / price)

        if target_quantity == 0 and weight > 0:
            skipped.append({
                "ticker": ticker, "reason": "below_one_share",
                "target_weight": weight, "price": price,
            })
            # 목표를 0으로 남기면 다음 회차가 같은 주문을 또 시도한다. 보유가 있으면
            # 그대로 두고, 없으면 아예 목록에서 뺀다.
            if current == 0:
                continue
            target_quantity = current

        delta_weight = abs(target_quantity - current) * price / equity
        if 0 < delta_weight < min_trade_weight:
            skipped.append({
                "ticker": ticker, "reason": "below_min_trade",
                "delta_weight": delta_weight, "threshold": min_trade_weight,
            })
            target_quantity = current

        positions.append(TargetPosition(
            ticker=ticker,
            target_weight=weight,
            price=price,
            target_quantity=target_quantity,
            current_quantity=current,
        ))

    invested = sum(position.target_quantity * position.price for position in positions) / equity
    return SizingResult(positions=positions, skipped=skipped, invested_weight=invested)


__all__ = [
    "DEFAULT_MIN_TRADE_WEIGHT",
    "SizingResult",
    "TargetPosition",
    "size_portfolio",
]
