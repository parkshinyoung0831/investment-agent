"""대량 주문 시간 분할(TWAP) 집행 슬라이서.

단일 주문의 시장 충격(Market Impact)과 슬리피지를 최소화하기 위해,
지정된 시간 구간(Window) 동안 일정 간격으로 주문을 균등 분할하는 알고리즘 슬라이서.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from investment_agent.platform.serialization import ContractError, finite_float, normalize_ticker


@dataclass(frozen=True)
class TWAPSlice:
    """시간 분할 주문 1개 조각."""

    slice_index: int
    total_slices: int
    ticker: str
    side: str
    quantity: float
    scheduled_at: datetime
    limit_price: float | None = None

    def __post_init__(self) -> None:
        if self.slice_index < 0 or self.slice_index >= self.total_slices:
            raise ContractError("invalid slice index")
        if self.quantity <= 0.0:
            raise ContractError("slice quantity must be positive")
        if self.side not in {"buy", "sell"}:
            raise ContractError("side must be buy or sell")


class TWAPOrderSlicer:
    """TWAP 주문 분할기."""

    def __init__(
        self,
        default_slices: int = 4,
        default_duration_minutes: int = 60,
        min_slice_quantity: float = 1.0,
    ) -> None:
        self.default_slices = max(1, int(default_slices))
        self.default_duration_minutes = max(1, int(default_duration_minutes))
        self.min_slice_quantity = max(0.001, float(min_slice_quantity))

    def slice_order(
        self,
        *,
        ticker: str,
        side: str,
        total_quantity: float,
        start_time: datetime,
        num_slices: int | None = None,
        duration_minutes: int | None = None,
        limit_price: float | None = None,
    ) -> list[TWAPSlice]:
        """주문을 N개의 TWAP 슬라이스로 분할한다 (총 수량 보존)."""
        sym = normalize_ticker(ticker)
        act_side = str(side).lower().strip()
        qty = finite_float(total_quantity) or 0.0

        if not sym or sym == "CASH":
            raise ContractError("invalid ticker for slicing")
        if act_side not in {"buy", "sell"}:
            raise ContractError("side must be buy or sell")
        if qty <= 0.0:
            raise ContractError("total quantity must be positive")

        n_slices = max(1, int(num_slices or self.default_slices))
        dur_mins = max(1, int(duration_minutes or self.default_duration_minutes))

        # 만약 최소 분할 수량보다 작으면 1개 슬라이스로 즉시 반환
        if (qty / n_slices) < self.min_slice_quantity:
            n_slices = max(1, int(qty // self.min_slice_quantity))

        interval = timedelta(minutes=dur_mins / max(1, n_slices - 1)) if n_slices > 1 else timedelta(0)

        # 수량 분할 (마지막 슬라이스에서 반올림 오차 보정)
        base_qty = math.floor((qty / n_slices) * 10000.0) / 10000.0
        slices: list[TWAPSlice] = []
        allocated = 0.0

        for i in range(n_slices):
            sched = start_time + (interval * i)
            if i == n_slices - 1:
                # 마지막 슬라이스가 잔여 수량 전부 수용
                slice_qty = round(qty - allocated, 4)
            else:
                slice_qty = round(base_qty, 4)
            allocated += slice_qty

            slices.append(
                TWAPSlice(
                    slice_index=i,
                    total_slices=n_slices,
                    ticker=sym,
                    side=act_side,
                    quantity=slice_qty,
                    scheduled_at=sched,
                    limit_price=limit_price,
                )
            )

        return slices


__all__ = [
    "TWAPOrderSlicer",
    "TWAPSlice",
]
