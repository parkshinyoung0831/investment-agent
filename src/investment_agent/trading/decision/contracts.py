"""네이티브 투자 판단 계층이 공유하는 작고 검증 가능한 계약."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from investment_agent.trading.contracts import ContractError, json_value, parse_datetime
from investment_agent.platform.serialization import canonical_json

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
_REGIME_STATES = {"RISK_ON", "NORMAL", "RISK_OFF", "CRISIS"}
_TRENDS = {"up", "sideways", "down"}
_VOLATILITY_STATES = {"low", "normal", "high", "crisis"}
_LIQUIDITY_STATES = {"deep", "normal", "thin", "stressed"}
_MACRO_STATES = {"supportive", "neutral", "adverse", "unknown"}
_HORIZONS = {"1d": 1, "5d": 5, "20d": 20}


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ContractError(f"{field_name} must be finite")
    return parsed


def _between(value: Any, field_name: str, minimum: float, maximum: float) -> float:
    parsed = _finite(value, field_name)
    if not minimum <= parsed <= maximum:
        raise ContractError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


def _strings(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ContractError(f"{field_name} must contain strings")
    return tuple(item.strip() for item in value if item.strip())


def _ticker(value: str | None, field_name: str = "ticker") -> str | None:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).upper().strip()
    if not _TICKER_RE.fullmatch(normalized):
        raise ContractError(f"invalid {field_name}: {normalized}")
    return normalized


@dataclass(frozen=True)
class MarketRegime:
    """종목별 판단보다 먼저 공유되는 시장 환경 snapshot이다."""

    as_of_at: str
    risk_state: str
    trend: str
    volatility_state: str
    liquidity_state: str
    macro_state: str
    event_risk: float
    confidence: float
    available_at: str
    source_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    regime_id: str = field(init=False)
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        as_of = parse_datetime(self.as_of_at).isoformat()
        available = parse_datetime(self.available_at).isoformat()
        if available > as_of:
            raise ContractError("market regime available_at cannot be after as_of_at")
        risk_state = str(self.risk_state).upper().strip()
        trend = str(self.trend).lower().strip()
        volatility_state = str(self.volatility_state).lower().strip()
        liquidity_state = str(self.liquidity_state).lower().strip()
        macro_state = str(self.macro_state).lower().strip()
        if risk_state not in _REGIME_STATES:
            raise ContractError(f"invalid risk_state: {risk_state}")
        if trend not in _TRENDS:
            raise ContractError(f"invalid trend: {trend}")
        if volatility_state not in _VOLATILITY_STATES:
            raise ContractError(f"invalid volatility_state: {volatility_state}")
        if liquidity_state not in _LIQUIDITY_STATES:
            raise ContractError(f"invalid liquidity_state: {liquidity_state}")
        if macro_state not in _MACRO_STATES:
            raise ContractError(f"invalid macro_state: {macro_state}")
        source_ids = tuple(sorted(_strings(self.source_ids, "source_ids")))
        identity = {
            "as_of_at": as_of,
            "risk_state": risk_state,
            "trend": trend,
            "volatility_state": volatility_state,
            "liquidity_state": liquidity_state,
            "macro_state": macro_state,
            "event_risk": _between(self.event_risk, "event_risk", 0.0, 1.0),
            "confidence": _between(self.confidence, "confidence", 0.0, 1.0),
            "available_at": available,
            "source_ids": source_ids,
            "metadata": dict(self.metadata),
        }
        input_hash = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        object.__setattr__(self, "as_of_at", as_of)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "risk_state", risk_state)
        object.__setattr__(self, "trend", trend)
        object.__setattr__(self, "volatility_state", volatility_state)
        object.__setattr__(self, "liquidity_state", liquidity_state)
        object.__setattr__(self, "macro_state", macro_state)
        object.__setattr__(self, "event_risk", identity["event_risk"])
        object.__setattr__(self, "confidence", identity["confidence"])
        object.__setattr__(self, "source_ids", source_ids)
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "input_hash", input_hash)
        object.__setattr__(self, "regime_id", f"regime_{input_hash[:24]}")

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class AnalystSignal:
    """Market/Fundamental/Macro/Event desk가 공통으로 반환하는 신호."""

    ticker: str
    as_of_at: str
    domain: str
    direction: float
    score: float
    confidence: float
    expected_return: float | None = None
    horizon: str = "5d"
    reasoning: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    model: str = "rule"
    version: str = "native-v1"

    def __post_init__(self) -> None:
        ticker = _ticker(self.ticker)
        if ticker is None:
            raise ContractError("analyst signal ticker is required")
        as_of = parse_datetime(self.as_of_at).isoformat()
        domain = str(self.domain).strip().lower()
        if not domain:
            raise ContractError("analyst signal domain is required")
        horizon = f"{self.horizon}d" if isinstance(self.horizon, int) else str(self.horizon).lower().strip()
        if horizon not in _HORIZONS:
            raise ContractError("analyst signal horizon must be 1d, 5d, or 20d")
        expected = None if self.expected_return is None else _finite(self.expected_return, "expected_return")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "as_of_at", as_of)
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "direction", _between(self.direction, "direction", -1.0, 1.0))
        object.__setattr__(self, "score", _between(self.score, "score", -1.0, 1.0))
        object.__setattr__(self, "confidence", _between(self.confidence, "confidence", 0.0, 1.0))
        object.__setattr__(self, "expected_return", expected)
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "reasoning", _strings(self.reasoning, "reasoning"))
        object.__setattr__(self, "evidence_ids", _strings(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "missing_data", _strings(self.missing_data, "missing_data"))
        object.__setattr__(self, "warnings", _strings(self.warnings, "warnings"))
        if not str(self.model).strip() or not str(self.version).strip():
            raise ContractError("analyst signal model and version are required")

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class ExpectedReturnSignal:
    """숫자 모델·desk·fusion이 portfolio에 넘기는 수익률 예측 계약이다."""

    ticker: str
    as_of_at: str
    expected_1d_return: float
    expected_5d_return: float
    expected_20d_return: float
    probability_up: float
    confidence: float
    uncertainty: float
    preferred_horizon: str
    model_id: str
    version: str
    major_positive_factors: tuple[str, ...] = ()
    major_negative_factors: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ticker = _ticker(self.ticker)
        if ticker is None:
            raise ContractError("expected-return ticker is required")
        as_of = parse_datetime(self.as_of_at).isoformat()
        horizon = str(self.preferred_horizon).lower().strip()
        if horizon not in _HORIZONS:
            raise ContractError("preferred_horizon must be 1d, 5d, or 20d")
        for name in ("expected_1d_return", "expected_5d_return", "expected_20d_return"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        object.__setattr__(self, "probability_up", _between(self.probability_up, "probability_up", 0.0, 1.0))
        object.__setattr__(self, "confidence", _between(self.confidence, "confidence", 0.0, 1.0))
        object.__setattr__(self, "uncertainty", _between(self.uncertainty, "uncertainty", 0.0, 1.0))
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "as_of_at", as_of)
        object.__setattr__(self, "preferred_horizon", horizon)
        object.__setattr__(self, "major_positive_factors", _strings(self.major_positive_factors, "major_positive_factors"))
        object.__setattr__(self, "major_negative_factors", _strings(self.major_negative_factors, "major_negative_factors"))
        object.__setattr__(self, "evidence_ids", _strings(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if not str(self.model_id).strip() or not str(self.version).strip():
            raise ContractError("model_id and version are required")

    @property
    def expected_return(self) -> float:
        """선호 horizon에 해당하는 예측값을 portfolio 계층에 제공한다."""
        return float(getattr(self, f"expected_{_HORIZONS[self.preferred_horizon]}d_return"))

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


__all__ = [
    "AnalystSignal",
    "ExpectedReturnSignal",
    "MarketRegime",
]
