"""토스 실계좌를 읽어 주문 제출 없는 수동 주문표를 만든다."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import secrets
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from investment_agent.platform.serialization import canonical_json, parse_datetime
from investment_agent.execution.orders.intents import CASH_SYMBOL, ExecutionIntent
from investment_agent.execution.brokers.toss import client as toss
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.planning import OrderPlan, TargetWeightOrderPlanner

_CONTRACT_VERSION = "toss-manual-v1"


def _positive_number(value: Any, *, field: str, allow_zero: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionSafetyError(f"invalid Toss {field}") from exc
    if not math.isfinite(number) or (number < 0 if allow_zero else number <= 0):
        raise ExecutionSafetyError(f"invalid Toss {field}")
    return number


def _finite_number(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionSafetyError(f"invalid Toss {field}") from exc
    if not math.isfinite(number):
        raise ExecutionSafetyError(f"invalid Toss {field}")
    return number


def _daily_profit_loss_usd(result: dict[str, Any]) -> float:
    """공식 holdings 요약의 USD 일간손익을 엄격히 읽는다."""
    daily = result.get("dailyProfitLoss")
    if not isinstance(daily, dict):
        raise ExecutionSafetyError("Toss holdings dailyProfitLoss is missing")
    amount = daily.get("amount")
    if not isinstance(amount, dict):
        raise ExecutionSafetyError("Toss holdings daily profit amount is missing")
    raw = amount.get("usd")
    # 미국 보유가 전혀 없을 때 공식 응답은 USD를 null로 줄 수 있다.
    if raw is None:
        if any(
            str(item.get("marketCountry") or "").upper() == "US"
            for item in result.get("items") or ()
            if isinstance(item, dict)
        ):
            raise ExecutionSafetyError("Toss USD daily profit is missing for US holdings")
        return 0.0
    return _finite_number(raw, field="USD daily profit/loss")


@dataclass(frozen=True)
class TossManualSnapshot:
    """S&P 500 미국주식 sleeve의 읽기 전용 계좌 스냅샷."""

    captured_at: str
    currency: str
    portfolio_value: float
    cash_buying_power: float
    current_quantities: dict[str, float]
    prices: dict[str, float]
    price_timestamps: dict[str, str | None]
    daily_profit_loss_usd: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "captured_at", parse_datetime(self.captured_at).isoformat())
        object.__setattr__(
            self,
            "price_timestamps",
            {
                str(symbol).upper(): (
                    parse_datetime(timestamp).isoformat() if timestamp is not None else None
                )
                for symbol, timestamp in self.price_timestamps.items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TossManualSnapshot":
        if not isinstance(value, dict):
            raise ExecutionSafetyError("Toss handoff snapshot must be an object")
        captured_at = str(value.get("captured_at") or "")
        try:
            parse_datetime(captured_at)
        except (TypeError, ValueError) as exc:
            raise ExecutionSafetyError("Toss handoff snapshot time is invalid") from exc
        currency = str(value.get("currency") or "").upper()
        if currency != "USD":
            raise ExecutionSafetyError("Toss handoff snapshot currency must be USD")
        quantities = value.get("current_quantities")
        prices = value.get("prices")
        timestamps = value.get("price_timestamps")
        if not all(isinstance(item, dict) for item in (quantities, prices, timestamps)):
            raise ExecutionSafetyError("Toss handoff snapshot mappings are invalid")
        parsed_quantities = {
            str(symbol).upper(): _positive_number(
                quantity, field=f"{symbol} holding quantity", allow_zero=True,
            )
            for symbol, quantity in quantities.items()
        }
        parsed_prices = {
            str(symbol).upper(): _positive_number(price, field=f"{symbol} price")
            for symbol, price in prices.items()
        }
        parsed_timestamps = {
            str(symbol).upper(): (str(timestamp) if timestamp is not None else None)
            for symbol, timestamp in timestamps.items()
        }
        if set(parsed_prices) != set(parsed_timestamps):
            raise ExecutionSafetyError("Toss handoff quote timestamps do not match prices")
        return cls(
            captured_at=parse_datetime(captured_at).isoformat(),
            currency=currency,
            portfolio_value=_positive_number(
                value.get("portfolio_value"), field="portfolio value",
            ),
            cash_buying_power=_positive_number(
                value.get("cash_buying_power"), field="cash buying power", allow_zero=True,
            ),
            current_quantities=dict(sorted(parsed_quantities.items())),
            prices=dict(sorted(parsed_prices.items())),
            price_timestamps=dict(sorted(parsed_timestamps.items())),
            daily_profit_loss_usd=_finite_number(
                value.get("daily_profit_loss_usd", 0.0),
                field="USD daily profit/loss",
            ),
        )


@dataclass(frozen=True)
class TossManualTicket:
    """토스 앱에서 사람이 확인할 주문 한 줄."""

    intent_id: str
    client_order_id: str
    expires_at: str
    symbol: str
    side: str
    current_quantity: float
    target_weight: float
    target_quantity: float
    order_quantity: float
    reference_price: float
    price_timestamp: str | None
    estimated_notional: float
    instruction: str = "MANUAL_REVIEW_ONLY"

    def __post_init__(self) -> None:
        object.__setattr__(self, "expires_at", parse_datetime(self.expires_at).isoformat())
        if self.price_timestamp is not None:
            object.__setattr__(
                self, "price_timestamp", parse_datetime(self.price_timestamp).isoformat()
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TossManualTicket":
        if not isinstance(value, dict):
            raise ExecutionSafetyError("Toss handoff ticket must be an object")
        try:
            ticket = cls(
                intent_id=str(value["intent_id"]),
                client_order_id=str(value["client_order_id"]),
                expires_at=parse_datetime(str(value["expires_at"])).isoformat(),
                symbol=str(value["symbol"]).upper(),
                side=str(value["side"]).lower(),
                current_quantity=_positive_number(
                    value["current_quantity"], field="current quantity", allow_zero=True,
                ),
                target_weight=_positive_number(
                    value["target_weight"], field="target weight", allow_zero=True,
                ),
                target_quantity=_positive_number(
                    value["target_quantity"], field="target quantity", allow_zero=True,
                ),
                order_quantity=_positive_number(value["order_quantity"], field="order quantity"),
                reference_price=_positive_number(value["reference_price"], field="reference price"),
                price_timestamp=(
                    str(value["price_timestamp"])
                    if value.get("price_timestamp") is not None else None
                ),
                estimated_notional=_positive_number(
                    value["estimated_notional"], field="estimated notional",
                ),
                instruction=str(value.get("instruction") or ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionSafetyError("Toss handoff ticket is incomplete") from exc
        if ticket.side not in {"buy", "sell"}:
            raise ExecutionSafetyError("Toss handoff ticket side is invalid")
        if ticket.symbol == CASH_SYMBOL or not ticket.symbol:
            raise ExecutionSafetyError("Toss handoff ticket symbol is invalid")
        if ticket.instruction != "MANUAL_REVIEW_ONLY":
            raise ExecutionSafetyError("Toss handoff instruction is invalid")
        return ticket


@dataclass(frozen=True)
class TossManualHandoff:
    """계좌 스냅샷과 결정적 주문표를 함께 묶은 내보내기 단위."""

    intent_id: str
    account_seq: int
    contract_version: str
    snapshot: TossManualSnapshot
    tickets: tuple[TossManualTicket, ...]
    manifest_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.account_seq, int) or self.account_seq <= 0:
            raise ExecutionSafetyError("Toss handoff account_seq must be positive")

    def identity(self) -> dict[str, Any]:
        """내보내지 않는 계좌 결박까지 포함한 manifest 원본이다."""
        return {
            "intent_id": self.intent_id,
            "account_binding": self.account_seq,
            "contract_version": self.contract_version,
            "snapshot": self.snapshot.to_dict(),
            "tickets": [ticket.to_dict() for ticket in self.tickets],
        }

    def recomputed_manifest_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.identity()).encode("utf-8")).hexdigest()

    def validate_manifest(self) -> None:
        """메모리에서 ticket을 바꾼 뒤 기존 승인을 재사용하지 못하게 한다."""
        if not re.fullmatch(r"[0-9a-f]{64}", self.manifest_hash):
            raise ExecutionSafetyError("invalid Toss handoff manifest hash")
        if not secrets.compare_digest(self.manifest_hash, self.recomputed_manifest_hash()):
            raise ExecutionSafetyError("Toss handoff manifest contents changed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "contract_version": self.contract_version,
            "snapshot": self.snapshot.to_dict(),
            "tickets": [ticket.to_dict() for ticket in self.tickets],
            "manifest_hash": self.manifest_hash,
            "disclaimer": "NON_EXECUTABLE_TOSS_MANUAL_ORDER_SHEET",
        }

    @classmethod
    def from_private_dict(
        cls,
        value: dict[str, Any],
        *,
        account_seq: int,
    ) -> "TossManualHandoff":
        """private DB의 계좌 결박과 공개 가능한 manifest를 다시 엄격히 결합한다."""
        if not isinstance(value, dict):
            raise ExecutionSafetyError("Toss handoff payload must be an object")
        raw_tickets = value.get("tickets")
        if not isinstance(raw_tickets, list):
            raise ExecutionSafetyError("Toss handoff tickets must be a list")
        handoff = cls(
            intent_id=str(value.get("intent_id") or ""),
            account_seq=account_seq,
            contract_version=str(value.get("contract_version") or ""),
            snapshot=TossManualSnapshot.from_dict(dict(value.get("snapshot") or {})),
            tickets=tuple(TossManualTicket.from_dict(dict(item)) for item in raw_tickets),
            manifest_hash=str(value.get("manifest_hash") or ""),
        )
        if handoff.contract_version != _CONTRACT_VERSION:
            raise ExecutionSafetyError("unsupported Toss handoff contract version")
        if not handoff.intent_id or any(
            ticket.intent_id != handoff.intent_id for ticket in handoff.tickets
        ):
            raise ExecutionSafetyError("Toss handoff intent identity is inconsistent")
        if not handoff.tickets:
            raise ExecutionSafetyError("Toss handoff has no orders")
        handoff.validate_manifest()
        return handoff


def _us_holdings(result: dict[str, Any]) -> dict[str, float]:
    quantities: dict[str, float] = {}
    for item in result.get("items") or []:
        if str(item.get("marketCountry") or "").upper() != "US":
            continue
        ticker = toss.from_toss_symbol(str(item.get("symbol") or ""))
        if not ticker:
            raise ExecutionSafetyError("Toss US holding has no symbol")
        quantity = _positive_number(
            item.get("quantity"),
            field=f"{ticker} holding quantity",
            allow_zero=True,
        )
        if quantity > 0:
            quantities[ticker] = quantity
    return quantities


def build_snapshot(
    intent: ExecutionIntent,
    *,
    account_seq: int,
    captured_at: datetime | None = None,
) -> TossManualSnapshot:
    """미체결 주문이 없는 계좌에서 USD sleeve의 최신 상태를 읽는다."""
    open_orders = toss.fetch_open_orders(account_seq)
    if open_orders:
        symbols = sorted({
            toss.from_toss_symbol(str(row.get("symbol") or ""))
            for row in open_orders
            if row.get("symbol")
        })
        suffix = f": {', '.join(symbols)}" if symbols else ""
        raise ExecutionSafetyError("Toss account has open orders" + suffix)

    holdings = toss.fetch_holdings(account_seq)
    current_quantities = _us_holdings(holdings)
    symbols = (set(intent.target_weights) - {CASH_SYMBOL}) | set(current_quantities)
    if not symbols:
        raise ExecutionSafetyError("execution intent has no risky symbols")
    prices, timestamps = toss.fetch_prices(symbols)
    cash = toss.fetch_buying_power(account_seq, currency="USD")
    holdings_value = math.fsum(
        quantity * prices[symbol]
        for symbol, quantity in current_quantities.items()
    )
    portfolio_value = cash + holdings_value
    if not math.isfinite(portfolio_value) or portfolio_value <= 0:
        raise ExecutionSafetyError("Toss USD sleeve portfolio value must be positive")

    now = (captured_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return TossManualSnapshot(
        captured_at=now.isoformat(),
        currency="USD",
        portfolio_value=portfolio_value,
        cash_buying_power=cash,
        current_quantities=dict(sorted(current_quantities.items())),
        prices=dict(sorted(prices.items())),
        price_timestamps=dict(sorted(timestamps.items())),
        daily_profit_loss_usd=_daily_profit_loss_usd(holdings),
    )


def prepare_handoff(
    intent: ExecutionIntent,
    *,
    account_seq: int,
    eligible_buy_symbols: set[str],
    planner: TargetWeightOrderPlanner,
    required_mode: str = "paper",
    now: datetime | None = None,
) -> TossManualHandoff:
    """토스에 주문하지 않고 동일 입력에서 같은 수동 주문표를 만든다."""
    TargetWeightOrderPlanner.validate_intent(
        intent,
        now=now,
        required_mode=required_mode,
    )
    snapshot = build_snapshot(intent, account_seq=account_seq, captured_at=now)
    plans = planner.plan(
        intent,
        portfolio_value=snapshot.portfolio_value,
        current_quantities=snapshot.current_quantities,
        prices=snapshot.prices,
        eligible_buy_symbols=eligible_buy_symbols,
        required_mode=required_mode,
        now=now,
    )
    tickets = tuple(_ticket(intent, snapshot, plan) for plan in plans)
    handoff = TossManualHandoff(
        intent_id=intent.intent_id,
        account_seq=account_seq,
        contract_version=_CONTRACT_VERSION,
        snapshot=snapshot,
        tickets=tickets,
        manifest_hash="0" * 64,
    )
    return replace(handoff, manifest_hash=handoff.recomputed_manifest_hash())


def _ticket(
    intent: ExecutionIntent,
    snapshot: TossManualSnapshot,
    plan: OrderPlan,
) -> TossManualTicket:
    target_weight = float(intent.target_weights.get(plan.symbol, 0.0))
    target_quantity = snapshot.portfolio_value * target_weight / plan.reference_price
    return TossManualTicket(
        intent_id=intent.intent_id,
        client_order_id=plan.client_order_id,
        expires_at=intent.expires_at,
        symbol=plan.symbol,
        side=plan.side,
        current_quantity=float(snapshot.current_quantities.get(plan.symbol, 0.0)),
        target_weight=target_weight,
        target_quantity=target_quantity,
        order_quantity=plan.quantity,
        reference_price=plan.reference_price,
        price_timestamp=snapshot.price_timestamps.get(plan.symbol),
        estimated_notional=plan.notional,
    )


def export_handoff(
    handoff: TossManualHandoff,
    *,
    output_dir: Path,
    confirm: str,
) -> tuple[Path, Path]:
    """정확한 intent ID 재입력 후에만 CSV와 manifest를 원자적으로 쓴다."""
    handoff.validate_manifest()
    if confirm != handoff.intent_id:
        raise ExecutionSafetyError("--confirm must exactly match --intent-id")
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", handoff.intent_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{safe_id}.csv"
    manifest_path = output_dir / f"{safe_id}.manifest.json"

    fieldnames = list(TossManualTicket.__dataclass_fields__)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for ticket in handoff.tickets:
        writer.writerow(ticket.to_dict())
    _atomic_write(csv_path, buffer.getvalue())
    _atomic_write(
        manifest_path,
        json.dumps(handoff.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return csv_path, manifest_path


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="")
    temporary.replace(path)
