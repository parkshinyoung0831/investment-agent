"""분석 배치의 완전성과 종목 의견 기록의 순수 계약. System Portfolio는 이 기록을 논지로 읽는다."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from investment_agent.trading.contracts import ContractError, json_value, parse_datetime
from investment_agent.trading.portfolio.contracts import SecurityProposal
from investment_agent.platform.serialization import stable_id
from investment_agent.portfolio_weights import CASH_SYMBOL

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


def _symbols(values: Iterable[str], field_name: str, *, required: bool = False) -> tuple[str, ...]:
    raw = tuple(values)
    if any(not isinstance(value, str) for value in raw):
        raise ContractError(f"{field_name} must contain strings")
    normalized_values = tuple(value.upper().strip() for value in raw if value.strip())
    invalid = [value for value in normalized_values if value == CASH_SYMBOL or not _SYMBOL_RE.fullmatch(value)]
    if invalid:
        raise ContractError(f"{field_name} contains invalid symbols: {sorted(invalid)}")
    if len(normalized_values) != len(set(normalized_values)):
        raise ContractError(f"{field_name} contains duplicate symbols")
    normalized = tuple(sorted(normalized_values))
    if required and not normalized:
        raise ContractError(f"{field_name} must not be empty")
    return normalized


@dataclass(frozen=True)
class SignalBatch:
    """한 분석 회차에서 요청·성공·실패·미완료 종목을 고정한다."""

    batch_id: str
    as_of_at: str
    completed_at: str
    requested_symbols: tuple[str, ...]
    successful_symbols: tuple[str, ...]
    failed_symbols: tuple[str, ...] = ()
    model_artifact_id: str | None = None

    def __post_init__(self) -> None:
        batch_id = str(self.batch_id).strip()
        if not batch_id:
            raise ContractError("batch_id is required")
        as_of_at = parse_datetime(self.as_of_at).isoformat()
        completed_at = parse_datetime(self.completed_at).isoformat()
        if parse_datetime(completed_at) < parse_datetime(as_of_at):
            raise ContractError("signal batch completed_at cannot precede as_of_at")
        requested = _symbols(self.requested_symbols, "requested_symbols", required=True)
        successful = _symbols(self.successful_symbols, "successful_symbols")
        failed = _symbols(self.failed_symbols, "failed_symbols")
        requested_set = set(requested)
        if not set(successful) <= requested_set or not set(failed) <= requested_set:
            raise ContractError("signal batch outcomes must be requested symbols")
        overlap = set(successful) & set(failed)
        if overlap:
            raise ContractError("signal batch success and failure symbols overlap")
        artifact_id = (
            str(self.model_artifact_id).strip()
            if self.model_artifact_id is not None else None
        )
        if artifact_id == "":
            raise ContractError("model_artifact_id cannot be empty")
        object.__setattr__(self, "batch_id", batch_id)
        object.__setattr__(self, "as_of_at", as_of_at)
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(self, "requested_symbols", requested)
        object.__setattr__(self, "successful_symbols", successful)
        object.__setattr__(self, "failed_symbols", failed)
        object.__setattr__(self, "model_artifact_id", artifact_id)

    @property
    def pending_symbols(self) -> tuple[str, ...]:
        classified = set(self.successful_symbols) | set(self.failed_symbols)
        return tuple(symbol for symbol in self.requested_symbols if symbol not in classified)

    @property
    def is_complete(self) -> bool:
        """모든 요청이 성공한 배치만 실행 후보가 될 수 있다."""
        return (
            not self.failed_symbols
            and not self.pending_symbols
            and self.successful_symbols == self.requested_symbols
        )

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class SignalRecord:
    """SecurityProposal의 생성 배치와 유효기간을 묶는다."""

    batch_id: str
    proposal: SecurityProposal
    recorded_at: str
    expires_at: str
    case_key: str | None = None
    signal_id: str = field(init=False)

    def __post_init__(self) -> None:
        batch_id = str(self.batch_id).strip()
        if not batch_id or not isinstance(self.proposal, SecurityProposal):
            raise ContractError("signal record requires batch_id and SecurityProposal")
        recorded_at = parse_datetime(self.recorded_at).isoformat()
        expires_at = parse_datetime(self.expires_at).isoformat()
        proposal_time = parse_datetime(self.proposal.as_of_at)
        if parse_datetime(recorded_at) < proposal_time:
            raise ContractError("signal recorded_at cannot precede proposal as_of_at")
        if parse_datetime(expires_at) <= parse_datetime(recorded_at):
            raise ContractError("signal expires_at must be after recorded_at")
        case_key = str(self.case_key).strip() if self.case_key is not None else None
        case_key = case_key or None
        object.__setattr__(self, "batch_id", batch_id)
        object.__setattr__(self, "recorded_at", recorded_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "case_key", case_key)
        identity = {
            "batch_id": batch_id,
            "proposal": self.proposal.to_dict(),
            "recorded_at": recorded_at,
            "expires_at": expires_at,
            "case_key": case_key,
        }
        object.__setattr__(self, "signal_id", stable_id("signal", identity))

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "batch_id": self.batch_id,
            "proposal": self.proposal.to_dict(),
            "recorded_at": self.recorded_at,
            "expires_at": self.expires_at,
            "case_key": self.case_key,
        }


__all__ = ["SignalBatch", "SignalRecord"]
