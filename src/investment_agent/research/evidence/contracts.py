"""PIT 증거 한 건과 종목별 묶음. 미래 정보가 섞이면 생성 단계에서 거절한다."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from investment_agent.platform.serialization import ContractError, json_value, parse_datetime

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


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


__all__ = ["EvidenceBundle", "EvidenceItem"]
