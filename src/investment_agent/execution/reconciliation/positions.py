"""보유수량 대사 — 직전 관측 이후 수량 변화를 우리 주문의 체결량만으로 설명할 수 있는가.

주문 상태 대사는 우리가 낸 주문이 어떻게 됐는지만 본다. 앱에서 직접 산 주식, 앱에서 이미
체결된 매도, 액면분할처럼 우리 원장을 거치지 않은 변화는 거기서 보이지 않고, 그 상태에서
다음 주문 수량을 계산하면 틀린 계좌를 기준으로 주문하게 된다.

현금은 여기서 대사하지 않는다. 배당·입출금·환전·수수료 정산이 모두 현금을 움직여서
주문 체결만으로 설명하려 하면 정상 상황에서도 계속 불일치가 난다. 수량은 그런 사건이
분할·합병뿐이라 설명되지 않는 변화를 곧 위험 신호로 볼 수 있다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

# 토스 소수점 정밀도(6자리)보다 한 자리 작다. 부동소수 누적 오차만 흡수한다.
QUANTITY_TOLERANCE = 1e-7


@dataclass(frozen=True)
class OrderFill:
    ticker: str
    side: str
    filled_quantity: float

    def __post_init__(self) -> None:
        if self.side not in {"buy", "sell"}:
            raise ValueError(f"order side must be buy or sell: {self.side}")
        if not math.isfinite(self.filled_quantity) or self.filled_quantity < 0:
            raise ValueError("filled quantity must be finite and non-negative")


@dataclass(frozen=True)
class PositionBaseline:
    """마지막으로 설명된 계좌 상태와 그때까지 반영한 주문별 누적 체결량."""

    observed_at: str
    positions: Mapping[str, float]
    order_fills: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"observed_at": self.observed_at, "positions": dict(sorted(self.positions.items())),
                "order_fills": dict(sorted(self.order_fills.items()))}

    @classmethod
    def from_dict(cls, value: Mapping) -> "PositionBaseline":
        return cls(
            observed_at=str(value["observed_at"]),
            positions={str(k).upper(): float(v) for k, v in dict(value.get("positions") or {}).items()},
            order_fills={str(k): float(v) for k, v in dict(value.get("order_fills") or {}).items()},
        )


@dataclass(frozen=True)
class PositionMismatch:
    ticker: str
    expected_quantity: float
    broker_quantity: float

    @property
    def difference(self) -> float:
        return self.broker_quantity - self.expected_quantity

    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "expected_quantity": round(self.expected_quantity, 6),
                "broker_quantity": round(self.broker_quantity, 6), "difference": round(self.difference, 6)}


@dataclass(frozen=True)
class PositionReconciliation:
    mismatches: tuple[PositionMismatch, ...]
    next_baseline: PositionBaseline
    is_first_observation: bool = False


def reconcile_positions(
    baseline: PositionBaseline | None,
    *,
    broker_positions: Mapping[str, float],
    order_fills: Mapping[str, OrderFill],
    observed_at: str,
) -> PositionReconciliation:
    """직전 기준 + 그 뒤 우리 체결량 = 지금 broker 수량인지 종목마다 확인한다.

    기준이 없으면 지금을 기준으로 삼는다 — 첫 관측에서는 설명할 과거가 없다. 불일치가 나도
    다음 기준은 지금 broker 상태로 옮긴다. 같은 변화를 매 주기 다시 알리지 않고, 차단은
    호출자가 건 lockdown이 사람의 확인 전까지 유지한다.
    """
    current = {str(ticker).upper(): float(quantity) for ticker, quantity in broker_positions.items()}
    if any(not math.isfinite(value) or value < 0 for value in current.values()):
        raise ValueError("broker positions must be finite and non-negative")
    fills_now = {client_id: fill.filled_quantity for client_id, fill in order_fills.items()}
    if baseline is None:
        return PositionReconciliation(
            mismatches=(),
            next_baseline=PositionBaseline(observed_at=observed_at, positions=current, order_fills=fills_now),
            is_first_observation=True,
        )
    expected = dict(baseline.positions)
    for client_id, fill in order_fills.items():
        delta = fill.filled_quantity - baseline.order_fills.get(client_id, 0.0)
        if delta < -QUANTITY_TOLERANCE:
            raise ValueError(f"cumulative filled quantity decreased for {client_id}")
        signed = delta if fill.side == "buy" else -delta
        expected[fill.ticker.upper()] = expected.get(fill.ticker.upper(), 0.0) + signed
    mismatches = tuple(
        PositionMismatch(ticker, expected.get(ticker, 0.0), current.get(ticker, 0.0))
        for ticker in sorted(set(expected) | set(current))
        if abs(current.get(ticker, 0.0) - expected.get(ticker, 0.0)) > QUANTITY_TOLERANCE
    )
    # 조회 창에서 빠진 옛 주문의 체결량은 기준에 남겨 두어야 다시 나타났을 때 이중 반영하지 않는다.
    carried = {**baseline.order_fills, **fills_now}
    return PositionReconciliation(
        mismatches=mismatches,
        next_baseline=PositionBaseline(observed_at=observed_at, positions=current, order_fills=carried),
    )


__all__ = [
    "OrderFill",
    "PositionBaseline",
    "PositionMismatch",
    "PositionReconciliation",
    "QUANTITY_TOLERANCE",
    "reconcile_positions",
]
