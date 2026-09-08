"""오프라인 weight-centric 백테스트의 입력·장부 계약."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping

from investment_agent.trading.contracts import json_value, parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL, validated_weights

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
_COHORT_MODES = {"point_in_time", "current_cohort"}
_ACTION_KINDS = {"split", "dividend"}


class BacktestSafetyError(RuntimeError):
    """결측·거래중단·시간 오류 때문에 장부 생성을 중단해야 하는 경우다."""


def _date(value: str | date, field_name: str) -> str:
    """달력 날짜를 정규 ISO 문자열로 검증한다."""
    try:
        parsed = value if isinstance(value, date) else date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc
    return parsed.isoformat()


def _symbol(value: str) -> str:
    symbol = str(value).upper().strip()
    if symbol == CASH_SYMBOL or not _TICKER_RE.fullmatch(symbol):
        raise ValueError(f"invalid risky-asset symbol: {symbol}")
    return symbol


def _finite(value: float, field_name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or (positive and parsed <= 0.0):
        qualifier = "finite and positive" if positive else "finite"
        raise ValueError(f"{field_name} must be {qualifier}")
    return parsed


def stable_hash(value: Any) -> str:
    """정렬된 JSON 표현에 SHA-256을 적용한다."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MarketBar:
    """기업행사 장부와 함께 쓸 당시 실제 호가 기준의 비조정 OHLCV다."""

    symbol: str
    session_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    halted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _symbol(self.symbol))
        object.__setattr__(self, "session_date", _date(self.session_date, "session_date"))
        prices = {
            name: _finite(getattr(self, name), name, positive=True)
            for name in ("open", "high", "low", "close")
        }
        volume = _finite(self.volume, "volume")
        if volume < 0.0:
            raise ValueError("volume must be non-negative")
        if prices["low"] > min(prices["open"], prices["close"]):
            raise ValueError("bar low cannot exceed open or close")
        if prices["high"] < max(prices["open"], prices["close"]):
            raise ValueError("bar high cannot be below open or close")
        if prices["high"] < prices["low"]:
            raise ValueError("bar high cannot be below low")
        for name, value in prices.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "volume", volume)
        if not isinstance(self.halted, bool):
            raise ValueError("halted must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class CorporateAction:
    """장 시작 전에 포지션에 적용할 split 또는 현금배당이다."""

    symbol: str
    effective_date: str
    kind: str
    value: float
    action_id: str = ""

    def __post_init__(self) -> None:
        symbol = _symbol(self.symbol)
        effective_date = _date(self.effective_date, "effective_date")
        if self.kind not in _ACTION_KINDS:
            raise ValueError(f"unsupported corporate action: {self.kind}")
        value = _finite(self.value, "value", positive=True)
        identity = {
            "symbol": symbol,
            "effective_date": effective_date,
            "kind": self.kind,
            "value": value,
        }
        expected = f"action_{stable_hash(identity)[:24]}"
        if self.action_id and self.action_id != expected:
            raise ValueError("action_id does not match corporate action content")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "effective_date", effective_date)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "action_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class UniverseSnapshot:
    """해당 날짜부터 신규·추가 매수가 허용된 point-in-time 종목 집합이다."""

    effective_date: str
    symbols: tuple[str, ...]
    source_id: str

    def __post_init__(self) -> None:
        effective_date = _date(self.effective_date, "effective_date")
        normalized_symbols = tuple(_symbol(item) for item in self.symbols)
        if len(normalized_symbols) != len(set(normalized_symbols)):
            raise ValueError("universe snapshot contains duplicate symbols")
        symbols = tuple(sorted(normalized_symbols))
        if not symbols:
            raise ValueError("universe snapshot must contain at least one symbol")
        if not str(self.source_id).strip():
            raise ValueError("source_id is required")
        object.__setattr__(self, "effective_date", effective_date)
        object.__setattr__(self, "symbols", symbols)

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class WeightPoint:
    """t에 결정되어 명시한 다음 거래일 시가부터 유효한 전체 포트폴리오 비중이다."""

    point_id: str
    decided_at: str
    effective_date: str
    weights: dict[str, float]
    source_id: str
    case_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        decided_at = parse_datetime(self.decided_at).isoformat()
        effective_date = _date(self.effective_date, "effective_date")
        if date.fromisoformat(effective_date) <= parse_datetime(decided_at).date():
            raise ValueError("effective_date must be after the decision date")
        if not str(self.source_id).strip():
            raise ValueError("source_id is required")
        weights = validated_weights(self.weights)
        case_keys = tuple(sorted({str(item).strip() for item in self.case_keys if str(item).strip()}))
        identity = {
            "decided_at": decided_at,
            "effective_date": effective_date,
            "weights": weights,
            "source_id": self.source_id,
            "case_keys": case_keys,
        }
        expected = f"weight_{stable_hash(identity)[:24]}"
        if self.point_id and self.point_id != expected:
            raise ValueError("point_id does not match weight point content")
        object.__setattr__(self, "point_id", expected)
        object.__setattr__(self, "decided_at", decided_at)
        object.__setattr__(self, "effective_date", effective_date)
        object.__setattr__(self, "weights", weights)
        object.__setattr__(self, "case_keys", case_keys)

    @classmethod
    def create(
        cls,
        *,
        decided_at: str,
        effective_date: str,
        weights: Mapping[str, float],
        source_id: str,
        case_keys: Iterable[str] = (),
    ) -> "WeightPoint":
        return cls(
            point_id="",
            decided_at=decided_at,
            effective_date=effective_date,
            weights=dict(weights),
            source_id=source_id,
            case_keys=tuple(case_keys),
        )

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class BacktestConfig:
    """동일 입력에서 체결 결과를 바꾸는 엔진 설정이다."""

    initial_cash: float = 100_000.0
    quantity_decimals: int = 6
    cohort_mode: str = "point_in_time"
    periods_per_year: int = 252
    risk_free_rate: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "initial_cash", _finite(self.initial_cash, "initial_cash", positive=True))
        if not isinstance(self.quantity_decimals, int) or not 0 <= self.quantity_decimals <= 8:
            raise ValueError("quantity_decimals must be an integer between 0 and 8")
        if self.cohort_mode not in _COHORT_MODES:
            raise ValueError(f"invalid cohort_mode: {self.cohort_mode}")
        if not isinstance(self.periods_per_year, int) or self.periods_per_year < 1:
            raise ValueError("periods_per_year must be a positive integer")
        object.__setattr__(self, "risk_free_rate", _finite(self.risk_free_rate, "risk_free_rate"))
        if self.risk_free_rate <= -1.0:
            raise ValueError("risk_free_rate must be greater than -1")

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class BacktestRequest:
    """네트워크나 DB 없이 재생할 수 있는 완전한 백테스트 입력이다."""

    sessions: tuple[str, ...]
    bars: tuple[MarketBar, ...]
    weight_points: tuple[WeightPoint, ...]
    universe_snapshots: tuple[UniverseSnapshot, ...]
    corporate_actions: tuple[CorporateAction, ...] = ()
    config: BacktestConfig = field(default_factory=BacktestConfig)

    def __post_init__(self) -> None:
        normalized_sessions = tuple(_date(item, "sessions") for item in self.sessions)
        if len(normalized_sessions) != len(set(normalized_sessions)):
            raise ValueError("trading calendar contains duplicate sessions")
        sessions = tuple(sorted(normalized_sessions))
        bars = tuple(sorted(self.bars, key=lambda item: (item.session_date, item.symbol)))
        points = tuple(sorted(self.weight_points, key=lambda item: (item.effective_date, item.point_id)))
        snapshots = tuple(sorted(self.universe_snapshots, key=lambda item: (item.effective_date, item.source_id)))
        actions = tuple(sorted(
            self.corporate_actions,
            key=lambda item: (item.effective_date, item.symbol, item.kind, item.action_id),
        ))
        if not sessions or not bars or not points or not snapshots:
            raise ValueError(
                "sessions, bars, weight_points, and universe_snapshots must not be empty"
            )
        outside_calendar = sorted({item.session_date for item in bars} - set(sessions))
        if outside_calendar:
            raise ValueError(f"market bars are outside the explicit calendar: {outside_calendar}")
        bar_keys = [(item.session_date, item.symbol) for item in bars]
        if len(bar_keys) != len(set(bar_keys)):
            raise ValueError("duplicate market bar")
        effective_dates = [item.effective_date for item in points]
        if len(effective_dates) != len(set(effective_dates)):
            raise ValueError("only one weight point is allowed per effective session")
        snapshot_dates = [item.effective_date for item in snapshots]
        if len(snapshot_dates) != len(set(snapshot_dates)):
            raise ValueError("only one universe snapshot is allowed per effective date")
        action_ids = [item.action_id for item in actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("duplicate corporate action")
        if self.config.cohort_mode == "current_cohort" and len(snapshots) != 1:
            raise ValueError("current_cohort mode requires exactly one fixed universe snapshot")
        object.__setattr__(self, "sessions", sessions)
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "weight_points", points)
        object.__setattr__(self, "universe_snapshots", snapshots)
        object.__setattr__(self, "corporate_actions", actions)

    @property
    def data_hash(self) -> str:
        return stable_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessions": list(self.sessions),
            "bars": [item.to_dict() for item in self.bars],
            "weight_points": [item.to_dict() for item in self.weight_points],
            "universe_snapshots": [item.to_dict() for item in self.universe_snapshots],
            "corporate_actions": [item.to_dict() for item in self.corporate_actions],
            "config": self.config.to_dict(),
        }


@dataclass(frozen=True)
class OrderEvent:
    order_id: str
    point_id: str
    session_date: str
    symbol: str
    side: str
    quantity: float
    reference_price: float
    status: str = "filled"

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class FillEvent:
    fill_id: str
    order_id: str
    session_date: str
    symbol: str
    side: str
    quantity: float
    reference_price: float
    fill_price: float
    gross_notional: float
    fee: float
    slippage_cost: float

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class CashEvent:
    event_id: str
    session_date: str
    kind: str
    amount: float
    balance: float
    symbol: str | None = None
    reference_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class CorporateActionApplication:
    action_id: str
    session_date: str
    symbol: str
    kind: str
    value: float
    quantity_before: float
    quantity_after: float
    cash_amount: float

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class PositionSnapshot:
    session_date: str
    symbol: str
    quantity: float
    average_cost: float
    cost_basis: float
    market_price: float
    market_value: float
    unrealized_pnl: float

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class NavPoint:
    session_date: str
    cash: float
    market_value: float
    nav: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    dividends: float
    fees: float
    slippage: float
    gross_exposure: float

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class BacktestResult:
    """입력 hash와 모든 장부를 포함하는 재현 가능한 결과 artifact다."""

    input_hash: str
    artifact_hash: str
    engine_version: str
    research_only: bool
    research_reasons: tuple[str, ...]
    orders: tuple[OrderEvent, ...]
    fills: tuple[FillEvent, ...]
    cash_ledger: tuple[CashEvent, ...]
    corporate_actions: tuple[CorporateActionApplication, ...]
    positions: tuple[PositionSnapshot, ...]
    nav: tuple[NavPoint, ...]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_hash": self.input_hash,
            "artifact_hash": self.artifact_hash,
            "engine_version": self.engine_version,
            "research_only": self.research_only,
            "research_reasons": list(self.research_reasons),
            "orders": [item.to_dict() for item in self.orders],
            "fills": [item.to_dict() for item in self.fills],
            "cash_ledger": [item.to_dict() for item in self.cash_ledger],
            "corporate_actions": [item.to_dict() for item in self.corporate_actions],
            "positions": [item.to_dict() for item in self.positions],
            "nav": [item.to_dict() for item in self.nav],
            "metrics": json_value(self.metrics),
        }
