"""브로커 계좌의 변경 불가능한 포트폴리오 스냅샷 계약."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from investment_agent.platform.serialization import (
    ContractError, json_value, parse_datetime, stable_id,
)
from investment_agent.execution.orders.intents import CASH_SYMBOL, validated_weights

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _nonnegative_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ContractError(f"{field_name} must be a finite non-negative number")
    return parsed


@dataclass(frozen=True)
class PositionSnapshot:
    """한 시점의 long-only 보유 수량과 USD 평가액."""

    ticker: str
    quantity: float
    market_price: float
    market_value: float

    def __post_init__(self) -> None:
        ticker = str(self.ticker).upper().strip()
        if ticker == CASH_SYMBOL or not _SYMBOL_RE.fullmatch(ticker):
            raise ContractError(f"invalid position ticker: {ticker}")
        quantity = _nonnegative_number(self.quantity, f"{ticker}.quantity")
        price = _nonnegative_number(self.market_price, f"{ticker}.market_price")
        value = _nonnegative_number(self.market_value, f"{ticker}.market_value")
        if quantity <= 0.0:
            raise ContractError(f"{ticker}.quantity must be positive")
        if price <= 0.0 or value <= 0.0:
            raise ContractError(f"{ticker} requires a fresh positive price and market value")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "market_price", price)
        object.__setattr__(self, "market_value", value)

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class AccountSnapshot:
    """계좌 조회 결과에서 내용 기반 ID를 만드는 불변 snapshot."""

    broker: str
    account_id: str
    captured_at: str
    cash_value: float
    positions: tuple[PositionSnapshot, ...] = ()
    base_currency: str = "USD"
    open_order_ids: tuple[str, ...] = ()
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        broker = str(self.broker).lower().strip()
        account_id = str(self.account_id).strip()
        currency = str(self.base_currency).upper().strip()
        if not broker or not account_id:
            raise ContractError("broker and account_id are required")
        if not _CURRENCY_RE.fullmatch(currency):
            raise ContractError(f"invalid base currency: {currency}")
        captured_at = parse_datetime(self.captured_at).isoformat()
        cash_value = _nonnegative_number(self.cash_value, "cash_value")
        positions = tuple(self.positions)
        if any(not isinstance(position, PositionSnapshot) for position in positions):
            raise ContractError("positions must contain PositionSnapshot values")
        positions = tuple(sorted(positions, key=lambda position: position.ticker))
        tickers = [position.ticker for position in positions]
        if len(tickers) != len(set(tickers)):
            raise ContractError("account snapshot contains duplicate position tickers")
        raw_order_ids = tuple(self.open_order_ids)
        if any(not isinstance(value, str) for value in raw_order_ids):
            raise ContractError("open_order_ids must contain strings")
        normalized_order_ids = tuple(value.strip() for value in raw_order_ids if value.strip())
        if len(normalized_order_ids) != len(set(normalized_order_ids)):
            raise ContractError("open_order_ids must not contain duplicates")
        order_ids = tuple(sorted(normalized_order_ids))
        if cash_value + math.fsum(position.market_value for position in positions) <= 0.0:
            raise ContractError("account snapshot total value must be positive")

        object.__setattr__(self, "broker", broker)
        object.__setattr__(self, "account_id", account_id)
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "cash_value", cash_value)
        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "base_currency", currency)
        object.__setattr__(self, "open_order_ids", order_ids)
        identity = {
            "broker": broker,
            "account_id": account_id,
            "captured_at": captured_at,
            "cash_value": cash_value,
            "positions": [position.to_dict() for position in positions],
            "base_currency": currency,
            "open_order_ids": order_ids,
        }
        object.__setattr__(self, "snapshot_id", stable_id("portfolio_snapshot", identity))

    @property
    def total_value(self) -> float:
        """현금과 보유 평가액을 합친 스냅샷 기준 순자산."""
        return self.cash_value + math.fsum(position.market_value for position in self.positions)

    @property
    def weights(self) -> dict[str, float]:
        """CASH를 포함해 합이 1인 현재 포트폴리오 비중."""
        total = self.total_value
        weights = {
            position.ticker: position.market_value / total
            for position in self.positions
        }
        weights[CASH_SYMBOL] = self.cash_value / total
        return validated_weights(weights)

    def assert_usable(
        self,
        *,
        expected_account_id: str,
        as_of_at: str | datetime,
        max_age_seconds: float,
    ) -> None:
        """계좌와 freshness가 맞지 않으면 전체 포트폴리오 생성을 막는다."""
        if self.account_id != str(expected_account_id).strip():
            raise ContractError("portfolio snapshot account does not match requested account")
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, (int, float)):
            raise ContractError("max_age_seconds must be numeric")
        max_age = float(max_age_seconds)
        if not math.isfinite(max_age) or max_age <= 0.0:
            raise ContractError("max_age_seconds must be positive")
        decision_time = parse_datetime(as_of_at)
        captured_time = parse_datetime(self.captured_at)
        if captured_time > decision_time:
            raise ContractError("portfolio snapshot is from the future")
        age_seconds = (decision_time - captured_time).total_seconds()
        if age_seconds > max_age:
            raise ContractError(
                f"portfolio snapshot is stale: {age_seconds:.3f}s > {max_age:.3f}s"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "broker": self.broker,
            "account_id": self.account_id,
            "captured_at": self.captured_at,
            "cash_value": self.cash_value,
            "positions": [position.to_dict() for position in self.positions],
            "base_currency": self.base_currency,
            "open_order_ids": list(self.open_order_ids),
            "total_value": self.total_value,
            "weights": self.weights,
        }


__all__ = ["AccountSnapshot", "PositionSnapshot"]
