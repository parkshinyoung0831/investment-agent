"""LLM 입출력과 저장 행을 검증하는 엄격한 계약."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from investment_agent.platform.serialization import (
    ContractError,
    json_value,
    parse_datetime,
)

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
_ACTIONS = {"avoid", "watch", "open", "increase", "hold", "reduce", "exit"}
_STANCES = {"bearish", "neutral", "bullish"}


def _text_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContractError(f"{field_name} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def _number(value: Any, field_name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field_name} must be numeric")
    parsed = float(value)
    if not minimum <= parsed <= maximum:
        raise ContractError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    domain: str
    source: str
    observed_at: str
    available_at: str | None
    timing_status: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.domain or not self.source:
            raise ContractError("evidence id, domain, and source are required")
        if self.timing_status not in {"known", "unknown"}:
            raise ContractError("timing_status must be known or unknown")
        if self.timing_status == "known" and self.available_at is None:
            raise ContractError("known evidence requires available_at")
        if self.available_at is not None:
            parse_datetime(self.available_at)

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class EvidenceBundle:
    ticker: str
    as_of_at: str
    source_kind: str
    evidence: tuple[EvidenceItem, ...]
    missing_data: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _TICKER_RE.fullmatch(self.ticker):
            raise ContractError(f"invalid ticker: {self.ticker}")
        if self.source_kind not in {"live_shadow", "historical_replay"}:
            raise ContractError(f"invalid bundle source_kind: {self.source_kind}")
        as_of = parse_datetime(self.as_of_at)
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ContractError("duplicate evidence_id")
        for item in self.evidence:
            if item.available_at and parse_datetime(item.available_at) > as_of:
                raise ContractError(f"future evidence rejected: {item.evidence_id}")

    @property
    def evidence_ids(self) -> set[str]:
        return {item.evidence_id for item in self.evidence}

    @property
    def domains(self) -> set[str]:
        return {item.domain for item in self.evidence}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "as_of_at": self.as_of_at,
            "source_kind": self.source_kind,
            "evidence": [item.to_dict() for item in self.evidence],
            "missing_data": list(self.missing_data),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class Claim:
    text: str
    evidence_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], allowed_ids: set[str]) -> "Claim":
        text = str(data.get("text") or "").strip()
        if not text:
            raise ContractError("claim text is required")
        ids = tuple(_text_list(data.get("evidence_ids"), "claim.evidence_ids"))
        if not ids:
            raise ContractError("every claim must cite at least one evidence_id")
        unknown = set(ids) - allowed_ids
        if unknown:
            raise ContractError(f"claim cites unknown evidence: {sorted(unknown)}")
        return cls(text=text, evidence_ids=ids)


@dataclass(frozen=True)
class RoleAnalysis:
    role: str
    summary: str
    stance: str
    confidence: float
    claims: tuple[Claim, ...]
    risks: tuple[str, ...]
    missing_data: tuple[str, ...]

    @classmethod
    def from_dict(
        cls,
        role: str,
        data: Mapping[str, Any],
        allowed_ids: set[str],
    ) -> "RoleAnalysis":
        required = {"summary", "stance", "confidence", "claims", "risks", "missing_data"}
        missing = required - set(data)
        if missing:
            raise ContractError(f"{role} output missing fields: {sorted(missing)}")
        stance = str(data["stance"])
        if stance not in _STANCES:
            raise ContractError(f"invalid stance: {stance}")
        raw_claims = data["claims"]
        if not isinstance(raw_claims, list):
            raise ContractError("claims must be a list")
        return cls(
            role=role,
            summary=str(data["summary"]).strip(),
            stance=stance,
            confidence=_number(data["confidence"], "confidence", 0.0, 1.0),
            claims=tuple(Claim.from_dict(item, allowed_ids) for item in raw_claims),
            risks=tuple(_text_list(data["risks"], "risks")),
            missing_data=tuple(_text_list(data["missing_data"], "missing_data")),
        )

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class InvestmentDecision:
    ticker: str
    as_of_at: str
    horizon_days: int
    action: str
    probability_up: float
    expected_excess_return: float
    confidence: float
    target_risk_unit: float
    thesis: tuple[str, ...]
    bear_case: tuple[str, ...]
    catalysts: tuple[str, ...]
    invalidation: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    missing_data: tuple[str, ...]

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        ticker: str,
        as_of_at: str,
        allowed_ids: set[str],
    ) -> "InvestmentDecision":
        fields = {
            "ticker", "as_of_at", "horizon_days", "action", "probability_up",
            "expected_excess_return", "confidence", "target_risk_unit", "thesis",
            "bear_case", "catalysts", "invalidation", "evidence_ids", "missing_data",
        }
        missing = fields - set(data)
        extra = set(data) - fields
        if missing or extra:
            raise ContractError(f"decision field mismatch missing={sorted(missing)} extra={sorted(extra)}")
        if str(data["ticker"]).upper() != ticker:
            raise ContractError("decision ticker does not match bundle")
        if parse_datetime(str(data["as_of_at"])) != parse_datetime(as_of_at):
            raise ContractError("decision as_of_at does not match bundle")
        action = str(data["action"])
        if action not in _ACTIONS:
            raise ContractError(f"invalid action: {action}")
        horizon = data["horizon_days"]
        if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 252:
            raise ContractError("horizon_days must be an integer between 1 and 252")
        ids = tuple(_text_list(data["evidence_ids"], "evidence_ids"))
        unknown = set(ids) - allowed_ids
        if unknown:
            raise ContractError(f"decision cites unknown evidence: {sorted(unknown)}")
        expected = data["expected_excess_return"]
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            raise ContractError("expected_excess_return must be numeric")
        return cls(
            ticker=ticker,
            as_of_at=parse_datetime(as_of_at).isoformat(),
            horizon_days=horizon,
            action=action,
            probability_up=_number(data["probability_up"], "probability_up", 0.0, 1.0),
            expected_excess_return=float(expected),
            confidence=_number(data["confidence"], "confidence", 0.0, 1.0),
            target_risk_unit=_number(data["target_risk_unit"], "target_risk_unit", 0.0, 1.0),
            thesis=tuple(_text_list(data["thesis"], "thesis")),
            bear_case=tuple(_text_list(data["bear_case"], "bear_case")),
            catalysts=tuple(_text_list(data["catalysts"], "catalysts")),
            invalidation=tuple(_text_list(data["invalidation"], "invalidation")),
            evidence_ids=ids,
            missing_data=tuple(_text_list(data["missing_data"], "missing_data")),
        )

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class EvaluationResult:
    case_key: str
    horizon_days: int
    start_trade_date: str
    end_trade_date: str
    asset_return: float
    benchmark_return: float
    excess_return: float
    max_adverse_excursion: float
    max_favorable_excursion: float
    direction_correct: bool | None
    brier_score: float
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


ROLE_OUTPUT_SCHEMA: dict[str, Any] = {
    "summary": "string",
    "stance": "bearish|neutral|bullish",
    "confidence": "number 0..1",
    "claims": [{"text": "string", "evidence_ids": ["EV-..."]}],
    "risks": ["string"],
    "missing_data": ["string"],
}

DECISION_OUTPUT_SCHEMA: dict[str, Any] = {
    "ticker": "string",
    "as_of_at": "ISO-8601 timestamp copied exactly from input",
    "horizon_days": "integer",
    "action": "avoid|watch|open|increase|hold|reduce|exit",
    "probability_up": "number 0..1",
    "expected_excess_return": "decimal return vs SPY, e.g. 0.03",
    "confidence": "number 0..1",
    "target_risk_unit": "number 0..1; shadow recommendation only",
    "thesis": ["string"],
    "bear_case": ["string"],
    "catalysts": ["string"],
    "invalidation": ["string"],
    "evidence_ids": ["EV-..."],
    "missing_data": ["string"],
}
