"""LLM·RL·룰 전략이 공유하는 포트폴리오 비중 계약."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from investment_agent.platform.serialization import (
    ContractError, json_value, parse_datetime, stable_id,
)

CASH_SYMBOL = "CASH"
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
_SIGNALS = {"avoid", "watch", "open", "increase", "hold", "reduce", "exit"}
_SOURCES = {"llm", "ml", "rl", "rule", "optimizer"}
_STAGES = {"shadow", "backtest", "out_of_sample", "walk_forward", "paper", "live"}


def _probability(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise ContractError(f"{field_name} must be between 0 and 1")
    return parsed


def _strings(value: Any, field_name: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ContractError(f"{field_name} must be a list of strings")
    result = tuple(item.strip() for item in value if item.strip())
    if required and not result:
        raise ContractError(f"{field_name} must not be empty")
    return result


def validated_weights(weights: Mapping[str, Any], *, require_total: bool = True) -> dict[str, float]:
    """long-only 비중을 검증하고 현금 항목을 포함한 정렬 사본을 반환한다."""
    if not isinstance(weights, Mapping) or not weights:
        raise ContractError("weights must be a non-empty mapping")
    parsed: dict[str, float] = {}
    for raw_symbol, raw_weight in weights.items():
        symbol = str(raw_symbol).upper().strip()
        if symbol != CASH_SYMBOL and not _TICKER_RE.fullmatch(symbol):
            raise ContractError(f"invalid portfolio symbol: {symbol}")
        if symbol in parsed:
            raise ContractError(f"duplicate portfolio symbol: {symbol}")
        if isinstance(raw_weight, bool) or not isinstance(raw_weight, (int, float)):
            raise ContractError(f"weight for {symbol} must be numeric")
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight < 0.0 or weight > 1.0:
            raise ContractError(f"weight for {symbol} must be between 0 and 1")
        parsed[symbol] = weight
    parsed.setdefault(CASH_SYMBOL, 0.0)
    total = math.fsum(parsed.values())
    if require_total and not math.isclose(total, 1.0, abs_tol=1e-8):
        raise ContractError(f"weights including CASH must sum to 1, got {total:.12f}")
    return {symbol: parsed[symbol] for symbol in sorted(parsed)}


@dataclass(frozen=True)
class SecurityProposal:
    """종목 분석 결과다. 실제 주문 권한은 갖지 않는다."""

    ticker: str
    as_of_at: str
    signal: str
    probability_up: float
    confidence: float
    expected_excess_return: float
    target_weight: float
    reasoning: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    missing_data: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ticker = self.ticker.upper()
        if not _TICKER_RE.fullmatch(ticker):
            raise ContractError(f"invalid ticker: {ticker}")
        if self.signal not in _SIGNALS:
            raise ContractError(f"invalid signal: {self.signal}")
        parse_datetime(self.as_of_at)
        _probability(self.probability_up, "probability_up")
        _probability(self.confidence, "confidence")
        _probability(self.target_weight, "target_weight")
        if not math.isfinite(float(self.expected_excess_return)):
            raise ContractError("expected_excess_return must be finite")
        if not self.reasoning:
            raise ContractError("reasoning must not be empty")
        object.__setattr__(self, "ticker", ticker)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        ticker: str,
        as_of_at: str,
        allowed_evidence_ids: set[str],
    ) -> "SecurityProposal":
        fields = {
            "ticker", "as_of_at", "signal", "probability_up", "confidence", "expected_excess_return",
            "target_weight", "reasoning", "evidence_ids", "missing_data",
        }
        missing = fields - set(data)
        extra = set(data) - fields
        if missing or extra:
            raise ContractError(
                f"security proposal field mismatch missing={sorted(missing)} extra={sorted(extra)}"
            )
        if str(data["ticker"]).upper() != ticker.upper():
            raise ContractError("security proposal ticker does not match bundle")
        if parse_datetime(str(data["as_of_at"])) != parse_datetime(as_of_at):
            raise ContractError("security proposal as_of_at does not match bundle")
        evidence_ids = _strings(data["evidence_ids"], "evidence_ids")
        unknown = set(evidence_ids) - allowed_evidence_ids
        if unknown:
            raise ContractError(f"security proposal cites unknown evidence: {sorted(unknown)}")
        expected = data["expected_excess_return"]
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            raise ContractError("expected_excess_return must be numeric")
        return cls(
            ticker=ticker,
            as_of_at=parse_datetime(as_of_at).isoformat(),
            signal=str(data["signal"]),
            probability_up=_probability(data["probability_up"], "probability_up"),
            confidence=_probability(data["confidence"], "confidence"),
            expected_excess_return=float(expected),
            target_weight=_probability(data["target_weight"], "target_weight"),
            reasoning=_strings(data["reasoning"], "reasoning", required=True),
            evidence_ids=evidence_ids,
            missing_data=_strings(data["missing_data"], "missing_data"),
        )

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))
@dataclass(frozen=True)
class PortfolioProposal:
    """FinRL-X의 weight-centric 경계를 저장 가능한 형태로 엄격화한다."""

    proposal_id: str
    run_id: str
    source_type: str
    source_version: str
    stage: str
    as_of_at: str
    weights: dict[str, float]
    confidence: float
    reasoning: tuple[str, ...]
    case_keys: tuple[str, ...] = ()
    model_artifact_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.run_id or not self.source_version:
            raise ContractError("proposal_id, run_id, and source_version are required")
        if self.source_type not in _SOURCES:
            raise ContractError(f"invalid source_type: {self.source_type}")
        if self.stage not in _STAGES:
            raise ContractError(f"invalid stage: {self.stage}")
        parse_datetime(self.as_of_at)
        object.__setattr__(self, "weights", validated_weights(self.weights))
        object.__setattr__(self, "confidence", _probability(self.confidence, "confidence"))
        if not self.reasoning:
            raise ContractError("reasoning must not be empty")
        coverage = self.metadata.get("coverage")
        if coverage is not None and coverage not in {"partial_universe", "full_portfolio"}:
            raise ContractError("invalid portfolio coverage metadata")

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        source_type: str,
        source_version: str,
        stage: str,
        as_of_at: str,
        weights: Mapping[str, Any],
        confidence: float,
        reasoning: tuple[str, ...],
        case_keys: tuple[str, ...] = (),
        model_artifact_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "PortfolioProposal":
        normalized_metadata = dict(metadata or {})
        identity = {
            "run_id": run_id,
            "source_type": source_type,
            "source_version": source_version,
            "stage": stage,
            "as_of_at": parse_datetime(as_of_at).isoformat(),
            "weights": validated_weights(weights),
            "confidence": _probability(confidence, "confidence"),
            "reasoning": tuple(reasoning),
            "case_keys": tuple(case_keys),
            "model_artifact_id": model_artifact_id,
            "metadata": normalized_metadata,
        }
        return cls(
            proposal_id=stable_id("proposal", identity),
            run_id=run_id,
            source_type=source_type,
            source_version=source_version,
            stage=stage,
            as_of_at=identity["as_of_at"],
            weights=identity["weights"],
            confidence=confidence,
            reasoning=reasoning,
            case_keys=case_keys,
            model_artifact_id=model_artifact_id,
            metadata=normalized_metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))

@dataclass(frozen=True)
class RiskDecision:
    """변경 불가능한 Python 위험 규칙의 검증 결과."""

    risk_decision_id: str
    proposal_id: str
    policy_key: str
    policy_version: int
    policy_hash: str
    input_hash: str
    is_approved: bool
    approved_weights: dict[str, float] | None
    violations: tuple[str, ...]
    adjustments: tuple[str, ...]
    metrics: dict[str, Any] = field(default_factory=dict)
    decided_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        parse_datetime(self.decided_at)
        if self.policy_version < 1:
            raise ContractError("policy_version must be positive")
        for field_name, value in (("policy_hash", self.policy_hash), ("input_hash", self.input_hash)):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ContractError(f"{field_name} must be a sha256 hex digest")
        if self.is_approved:
            if self.approved_weights is None:
                raise ContractError("approved risk decision requires approved_weights")
            object.__setattr__(self, "approved_weights", validated_weights(self.approved_weights))
        elif self.approved_weights is not None:
            raise ContractError("rejected risk decision cannot carry approved_weights")
        if not isinstance(self.metrics, Mapping):
            raise ContractError("risk decision metrics must be an object")
        object.__setattr__(self, "metrics", json_value(dict(self.metrics)))

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))
