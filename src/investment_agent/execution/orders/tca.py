"""주문 결과의 arrival·spread·slippage·implementation shortfall 계산."""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from investment_agent.platform.serialization import ContractError, canonical_json, json_value, parse_datetime


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ContractError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or (positive and parsed <= 0.0):
        raise ContractError(f"{name} must be finite" + (" and positive" if positive else ""))
    return parsed


@dataclass(frozen=True)
class TCAReport:
    """한 order의 비용을 양수 cost convention으로 남긴다."""

    tca_id: str
    ticker: str
    side: str
    decision_price: float
    arrival_price: float
    bid: float | None
    ask: float | None
    mid: float | None
    fill_price: float
    quantity: float
    spread_cost: float
    slippage: float
    fees: float
    implementation_shortfall: float
    delay_cost: float
    participation_rate: float | None
    time_to_fill: float | None
    intent_id: str | None = None
    client_order_id: str | None = None
    broker_order_id: str | None = None
    source_kind: str = "paper"
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ticker = str(self.ticker).upper().strip()
        side = str(self.side).lower().strip()
        source = str(self.source_kind).lower().strip()
        if not ticker or side not in {"buy", "sell"} or source not in {"backtest", "paper", "live"}:
            raise ContractError("TCA identity is invalid")
        created_at = parse_datetime(self.created_at or "1970-01-01T00:00:00+00:00").isoformat()
        for name in ("decision_price", "arrival_price", "fill_price"):
            object.__setattr__(self, name, _finite(getattr(self, name), name, positive=True))
        object.__setattr__(self, "quantity", _finite(self.quantity, "quantity", positive=True))
        for name in ("bid", "ask", "mid"):
            value = getattr(self, name)
            object.__setattr__(self, name, None if value is None else _finite(value, name, positive=True))
        for name in ("spread_cost", "fees"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
            if getattr(self, name) < 0.0:
                raise ContractError(f"{name} must be non-negative")
        for name in ("slippage", "implementation_shortfall", "delay_cost"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        participation = self.participation_rate
        if participation is not None:
            participation = _finite(participation, "participation_rate")
            if participation < 0.0:
                raise ContractError("participation_rate must be non-negative")
        time_to_fill = self.time_to_fill
        if time_to_fill is not None:
            time_to_fill = _finite(time_to_fill, "time_to_fill")
            if time_to_fill < 0.0:
                raise ContractError("time_to_fill must be non-negative")
        expected_shortfall = self.slippage + self.delay_cost + self.fees
        if not math.isclose(self.implementation_shortfall, expected_shortfall, rel_tol=1e-10, abs_tol=1e-8):
            raise ContractError("TCA implementation_shortfall does not reconcile")
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise ContractError("TCA ask cannot be below bid")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "source_kind", source)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "participation_rate", participation)
        object.__setattr__(self, "time_to_fill", time_to_fill)
        object.__setattr__(self, "metadata", dict(self.metadata))
        if not str(self.tca_id).strip():
            raise ContractError("tca_id is required")

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


def _side_cost(side: str, before: float, after: float, quantity: float) -> float:
    return (after - before) * quantity if side == "buy" else (before - after) * quantity


def build_tca_report(
    *,
    ticker: str,
    side: str,
    decision_price: float,
    arrival_price: float,
    fill_price: float,
    quantity: float,
    fees: float = 0.0,
    bid: float | None = None,
    ask: float | None = None,
    mid: float | None = None,
    adv_notional: float | None = None,
    submitted_at: str | None = None,
    filled_at: str | None = None,
    intent_id: str | None = None,
    client_order_id: str | None = None,
    broker_order_id: str | None = None,
    source_kind: str = "paper",
    created_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TCAReport:
    """원시 가격·체결 결과에서 TCA를 한 번 계산한다."""
    side = str(side).lower().strip()
    if side not in {"buy", "sell"}:
        raise ContractError("side must be buy or sell")
    quantity = _finite(quantity, "quantity", positive=True)
    decision = _finite(decision_price, "decision_price", positive=True)
    arrival = _finite(arrival_price, "arrival_price", positive=True)
    fill = _finite(fill_price, "fill_price", positive=True)
    fee = _finite(fees, "fees")
    if fee < 0.0:
        raise ContractError("fees must be non-negative")
    spread_cost = abs(fill - float(mid if mid is not None else arrival)) * quantity if mid is not None else 0.0
    slippage = _side_cost(side, arrival, fill, quantity)
    delay_cost = _side_cost(side, decision, arrival, quantity)
    participation = None
    if adv_notional is not None:
        adv = _finite(adv_notional, "adv_notional", positive=True)
        participation = quantity * arrival / adv
    fill_time = None
    if submitted_at is not None or filled_at is not None:
        if submitted_at is None or filled_at is None:
            raise ContractError("submitted_at and filled_at must be provided together")
        fill_time = (parse_datetime(filled_at) - parse_datetime(submitted_at)).total_seconds()
        if fill_time < 0.0:
            raise ContractError("filled_at cannot precede submitted_at")
    identity = {
        "ticker": str(ticker).upper().strip(),
        "side": side,
        "decision_price": decision,
        "arrival_price": arrival,
        "fill_price": fill,
        "quantity": quantity,
        "fees": fee,
        "intent_id": intent_id,
        "client_order_id": client_order_id,
        "broker_order_id": broker_order_id,
        "source_kind": source_kind,
    }
    tca_id = "tca_" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24]
    return TCAReport(
        tca_id=tca_id,
        ticker=ticker,
        side=side,
        decision_price=decision,
        arrival_price=arrival,
        bid=bid,
        ask=ask,
        mid=mid,
        fill_price=fill,
        quantity=quantity,
        spread_cost=spread_cost,
        slippage=slippage,
        fees=fee,
        implementation_shortfall=slippage + delay_cost + fee,
        delay_cost=delay_cost,
        participation_rate=participation,
        time_to_fill=fill_time,
        intent_id=intent_id,
        client_order_id=client_order_id,
        broker_order_id=broker_order_id,
        source_kind=source_kind,
        created_at=created_at or "1970-01-01T00:00:00+00:00",
        metadata=metadata or {},
    )


__all__ = ["TCAReport", "build_tca_report"]
