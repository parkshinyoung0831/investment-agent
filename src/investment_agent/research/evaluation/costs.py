"""결정론적 수수료와 slippage 계산."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


def _non_negative(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return parsed


@dataclass(frozen=True)
class FillQuote:
    fill_price: float
    gross_notional: float
    fee: float
    slippage_cost: float


@dataclass(frozen=True)
class TransactionCostModel:
    """시가에 고정 bps 충격과 비례·최소 수수료를 적용한다."""

    commission_rate: float = 0.0005
    minimum_commission: float = 0.0
    slippage_bps: float = 5.0
    sell_fee_rate: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "commission_rate", "minimum_commission", "slippage_bps", "sell_fee_rate",
        ):
            object.__setattr__(self, name, _non_negative(getattr(self, name), name))
        if self.slippage_bps >= 10_000.0:
            raise ValueError("slippage_bps must be below 10000")

    def quote(self, *, side: str, quantity: float, reference_price: float) -> FillQuote:
        if side not in {"buy", "sell"}:
            raise ValueError(f"invalid side: {side}")
        quantity = float(quantity)
        reference_price = float(reference_price)
        if not math.isfinite(quantity) or quantity <= 0.0:
            raise ValueError("quantity must be finite and positive")
        if not math.isfinite(reference_price) or reference_price <= 0.0:
            raise ValueError("reference_price must be finite and positive")
        impact = self.slippage_bps / 10_000.0
        fill_price = reference_price * (1.0 + impact if side == "buy" else 1.0 - impact)
        gross = quantity * fill_price
        fee = max(self.minimum_commission, gross * self.commission_rate)
        if side == "sell":
            fee += gross * self.sell_fee_rate
        return FillQuote(
            fill_price=fill_price,
            gross_notional=gross,
            fee=fee,
            slippage_cost=abs(fill_price - reference_price) * quantity,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
