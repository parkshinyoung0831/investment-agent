"""모든 broker response를 AI와 분리된 canonical 실행 계약으로 바꾼다."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


class BrokerError(RuntimeError):
    pass


class BrokerOutcomeUnknown(BrokerError):
    """timeout/5xx 뒤 성공 여부를 조회·reconciliation해야 하는 상태다."""

    def __init__(self, client_order_id: str, message: str):
        super().__init__(message)
        self.client_order_id = client_order_id


@dataclass(frozen=True)
class BrokerAccount:
    broker: str
    account_hash: str
    currency: str
    equity: float
    cash: float
    buying_power: float
    captured_at: str


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    quantity: float
    average_price: float
    market_price: float
    market_value: float
    currency: str = "USD"


@dataclass(frozen=True)
class BrokerQuote:
    symbol: str
    bid: float | None
    ask: float | None
    last: float
    observed_at: str
    halted: bool = False


@dataclass(frozen=True)
class CanonicalOrderRequest:
    client_order_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    limit_price: float | None = None
    exchange: str = "NASD"

    def __post_init__(self) -> None:
        if not self.client_order_id.strip() or not self.symbol.strip():
            raise ValueError("client_order_id and symbol are required")
        if self.side not in {"buy", "sell"} or self.order_type not in {"limit", "market"}:
            raise ValueError("invalid canonical order side/type")
        if not math.isfinite(float(self.quantity)) or self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.order_type == "limit" and (
            self.limit_price is None or not math.isfinite(float(self.limit_price)) or self.limit_price <= 0
        ):
            raise ValueError("limit order requires a positive limit_price")


@dataclass(frozen=True)
class BrokerOrder:
    client_order_id: str
    broker_order_id: str
    symbol: str
    side: str
    quantity: float
    filled_quantity: float
    average_fill_price: float | None
    status: str
    submitted_at: str
    raw_status: str


@dataclass(frozen=True)
class BrokerFill:
    fill_id: str
    broker_order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    fee: float
    filled_at: str


class BrokerAdapter(Protocol):
    name: str
    mode: str

    def account(self) -> BrokerAccount: ...
    def positions(self) -> Sequence[BrokerPosition]: ...
    def cash(self) -> float: ...
    def quote(self, symbol: str, *, exchange: str = "NAS") -> BrokerQuote: ...
    def submit_order(self, order: CanonicalOrderRequest) -> BrokerOrder: ...
    def cancel_order(self, broker_order_id: str, *, symbol: str, quantity: float) -> BrokerOrder: ...
    def order_status(self, broker_order_id: str) -> BrokerOrder | None: ...
    def open_orders(self) -> Sequence[BrokerOrder]: ...
    def fills(self) -> Sequence[BrokerFill]: ...
    def reconciliation_snapshot(self) -> Mapping[str, Any]: ...


__all__ = [
    "BrokerAccount", "BrokerAdapter", "BrokerError", "BrokerFill", "BrokerOrder",
    "BrokerOutcomeUnknown", "BrokerPosition", "BrokerQuote", "CanonicalOrderRequest",
]
