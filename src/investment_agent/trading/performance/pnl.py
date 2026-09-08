"""거래 단위 손익의 결정론적 회계 계약."""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from investment_agent.platform.serialization import ContractError, canonical_json, json_value, parse_datetime


def _positive(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ContractError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ContractError(f"{name} must be finite and positive")
    return parsed


def _non_negative(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ContractError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ContractError(f"{name} must be finite and non-negative")
    return parsed


@dataclass(frozen=True)
class TradeOutcome:
    """한 거래의 gross/net PnL과 비용을 immutable하게 보관한다."""

    outcome_id: str
    ticker: str
    side: str
    entry_at: str
    exit_at: str
    quantity: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    fees: float
    execution_slippage: float
    net_pnl: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ticker = str(self.ticker).upper().strip()
        side = str(self.side).lower().strip()
        entry_at = parse_datetime(self.entry_at).isoformat()
        exit_at = parse_datetime(self.exit_at).isoformat()
        if not ticker or side not in {"buy", "sell"} or exit_at < entry_at:
            raise ContractError("trade outcome identity or time is invalid")
        quantity = _positive(self.quantity, "quantity")
        entry_price = _positive(self.entry_price, "entry_price")
        exit_price = _positive(self.exit_price, "exit_price")
        gross = float(self.gross_pnl)
        fees = _non_negative(self.fees, "fees")
        slippage = _non_negative(self.execution_slippage, "execution_slippage")
        net = float(self.net_pnl)
        if any(not math.isfinite(value) for value in (gross, net)):
            raise ContractError("trade outcome PnL must be finite")
        if not math.isclose(net, gross - fees - slippage, rel_tol=1e-10, abs_tol=1e-8):
            raise ContractError("trade outcome net_pnl does not reconcile")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "entry_at", entry_at)
        object.__setattr__(self, "exit_at", exit_at)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "entry_price", entry_price)
        object.__setattr__(self, "exit_price", exit_price)
        object.__setattr__(self, "gross_pnl", gross)
        object.__setattr__(self, "fees", fees)
        object.__setattr__(self, "execution_slippage", slippage)
        object.__setattr__(self, "net_pnl", net)
        object.__setattr__(self, "metadata", dict(self.metadata))
        if not str(self.outcome_id).strip():
            raise ContractError("outcome_id is required")

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


def make_trade_outcome(
    *,
    ticker: str,
    side: str,
    entry_at: str,
    exit_at: str,
    quantity: float,
    entry_price: float,
    exit_price: float,
    fees: float = 0.0,
    execution_slippage: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> TradeOutcome:
    """매수/매도 방향을 반영해 gross와 net PnL을 계산한다."""
    direction = 1.0 if str(side).lower().strip() == "buy" else -1.0
    gross = (float(exit_price) - float(entry_price)) * float(quantity) * direction
    stable_identity = {
        "ticker": str(ticker).upper().strip(),
        "side": str(side).lower().strip(),
        "entry_at": parse_datetime(entry_at).isoformat(),
        "exit_at": parse_datetime(exit_at).isoformat(),
        "quantity": float(quantity),
        "entry_price": float(entry_price),
        "exit_price": float(exit_price),
        "fees": float(fees),
        "execution_slippage": float(execution_slippage),
    }
    outcome_id = "outcome_" + hashlib.sha256(canonical_json(stable_identity).encode("utf-8")).hexdigest()[:24]
    return TradeOutcome(
        outcome_id=outcome_id,
        ticker=ticker,
        side=side,
        entry_at=entry_at,
        exit_at=exit_at,
        quantity=quantity,
        entry_price=entry_price,
        exit_price=exit_price,
        gross_pnl=gross,
        fees=fees,
        execution_slippage=execution_slippage,
        net_pnl=gross - float(fees) - float(execution_slippage),
        metadata=metadata or {},
    )


__all__ = ["TradeOutcome", "make_trade_outcome"]
