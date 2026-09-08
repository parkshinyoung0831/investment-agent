"""장기 투자 서류철(InvestmentDossier)의 저장·전달 계약."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.platform.serialization import canonical_json

DOSSIER_VERSION = "dossier-v1"

# 서류철 섹션은 고정 집합이다. 늘리거나 줄이면 version을 올린다 — 소비자가 섹션
# 유무로 분기하지 않고 missing_reason만 보게 하려는 것이다.
SECTION_IDS = (
    "price_risk",
    "valuation",
    "fundamentals",
    "estimates",
    "segments",
    "ownership",
    "macro_events",
    "external_live",
)

_SOURCE_KINDS = {"live_shadow", "historical_replay"}


@dataclass(frozen=True)
class DossierSection:
    """한 섹션의 요약 payload와 그것을 뒷받침하는 근거·시각이다.

    값이 있으면 `evidence_ids`와 `available_at`이 반드시 있고, 없으면
    `missing_reason`만 있다. 둘 다 있거나 둘 다 없는 상태는 계약 위반이다.
    """

    section_id: str
    title: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    available_at: str | None = None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        if self.section_id not in SECTION_IDS:
            raise ContractError(f"unknown dossier section: {self.section_id}")
        if not str(self.title).strip():
            raise ContractError("dossier section title is required")
        if self.missing_reason is not None:
            if self.payload or self.evidence_ids or self.available_at:
                raise ContractError(
                    f"missing dossier section cannot carry data: {self.section_id}"
                )
            object.__setattr__(self, "payload", MappingProxyType({}))
            return
        if not self.payload:
            raise ContractError(f"known dossier section requires a payload: {self.section_id}")
        if not self.evidence_ids:
            raise ContractError(f"known dossier section requires evidence: {self.section_id}")
        if not self.available_at:
            raise ContractError(f"known dossier section requires available_at: {self.section_id}")
        ids = tuple(sorted({str(value).strip() for value in self.evidence_ids if str(value).strip()}))
        if not ids:
            raise ContractError(f"known dossier section requires evidence: {self.section_id}")
        object.__setattr__(self, "evidence_ids", ids)
        object.__setattr__(self, "available_at", parse_datetime(self.available_at).isoformat())
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    @property
    def is_known(self) -> bool:
        return self.missing_reason is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "payload": dict(self.payload),
            "evidence_ids": list(self.evidence_ids),
            "available_at": self.available_at,
            "missing_reason": self.missing_reason,
        }


@dataclass(frozen=True)
class DossierQuality:
    """서류철을 믿을 수 있는 정도를 숫자와 문장으로 함께 남긴다."""

    usable_sections: tuple[str, ...]
    missing_sections: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def coverage_score(self) -> float:
        """LLM 판단에 쓸 수 있는 섹션 비율. 0으로 나누지 않는다."""
        total = len(SECTION_IDS)
        return round(len(self.usable_sections) / total, 4) if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "usable_sections": list(self.usable_sections),
            "missing_sections": list(self.missing_sections),
            "warnings": list(self.warnings),
            "coverage_score": self.coverage_score,
        }


@dataclass(frozen=True)
class InvestmentDossier:
    """한 종목·한 시점의 근거 묶음. LLM 요약과 ML feature가 공유하는 원본이다."""

    ticker: str
    as_of_at: str
    source_kind: str
    sections: tuple[DossierSection, ...]
    quality: DossierQuality
    provenance: Mapping[str, Any]
    dossier_version: str = DOSSIER_VERSION
    dossier_id: str = field(init=False)

    def __post_init__(self) -> None:
        ticker = str(self.ticker).upper().strip()
        if not ticker:
            raise ContractError("dossier ticker is required")
        if self.source_kind not in _SOURCE_KINDS:
            raise ContractError(f"invalid dossier source_kind: {self.source_kind}")
        as_of = parse_datetime(self.as_of_at)
        seen = [section.section_id for section in self.sections]
        if sorted(seen) != sorted(SECTION_IDS):
            raise ContractError(
                "dossier must carry every section exactly once; "
                f"missing={sorted(set(SECTION_IDS) - set(seen))} "
                f"duplicate={sorted({name for name in seen if seen.count(name) > 1})}"
            )
        for section in self.sections:
            if section.available_at and parse_datetime(section.available_at) > as_of:
                raise ContractError(
                    f"dossier section is not available at as_of_at: {section.section_id}"
                )
        ordered = tuple(
            sorted(self.sections, key=lambda item: SECTION_IDS.index(item.section_id))
        )
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "as_of_at", as_of.isoformat())
        object.__setattr__(self, "sections", ordered)
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))
        identity = {
            "ticker": ticker,
            "as_of_at": as_of.isoformat(),
            "source_kind": self.source_kind,
            "dossier_version": self.dossier_version,
            "sections": [section.to_dict() for section in ordered],
        }
        digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        object.__setattr__(self, "dossier_id", f"dossier_{digest[:24]}")

    def section(self, section_id: str) -> DossierSection:
        for item in self.sections:
            if item.section_id == section_id:
                return item
        raise KeyError(section_id)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(sorted({
            evidence_id
            for section in self.sections
            for evidence_id in section.evidence_ids
        }))

    def to_dict(self) -> dict[str, Any]:
        return {
            "dossier_id": self.dossier_id,
            "dossier_version": self.dossier_version,
            "ticker": self.ticker,
            "as_of_at": self.as_of_at,
            "source_kind": self.source_kind,
            "sections": [section.to_dict() for section in self.sections],
            "quality": self.quality.to_dict(),
            "provenance": dict(self.provenance),
        }


def build_quality(
    sections: Sequence[DossierSection],
    *,
    warnings: Sequence[str] = (),
) -> DossierQuality:
    """섹션 상태에서 품질 요약을 만든다."""
    usable = tuple(section.section_id for section in sections if section.is_known)
    missing = tuple(section.section_id for section in sections if not section.is_known)
    return DossierQuality(
        usable_sections=usable,
        missing_sections=missing,
        warnings=tuple(dict.fromkeys(str(value) for value in warnings if str(value).strip())),
    )


__all__ = [
    "DOSSIER_VERSION",
    "SECTION_IDS",
    "DossierQuality",
    "DossierSection",
    "InvestmentDossier",
    "build_quality",
]
