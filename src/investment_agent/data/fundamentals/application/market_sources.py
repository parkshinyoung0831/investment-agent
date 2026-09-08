"""시장 예상치·실적 보도자료 원천 포트."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class PressReleaseDocument:
    """8-K 실적 보도자료에서 안전하게 읽을 수 있는 원천값 묶음."""

    html: str | None
    url: str | None
    revenue_actual: float | None = None
    operating_income_actual: float | None = None
    net_income_actual: float | None = None
    guidance_summary: str | None = None


class PressReleaseSource(Protocol):
    def press_release_document(
        self,
        cik: str | int,
        accession_no: str,
        primary_document: str | None,
    ) -> PressReleaseDocument: ...




class ConsensusSource(Protocol):
    """애널리스트 컨센서스 원천."""

    def fetch_consensus(self, ticker: str, *, today: date) -> dict: ...


class ReportedEarningsSource(Protocol):
    """발표된 조정 EPS(실제·예상) 원천."""

    def fetch_reported_earnings(self, ticker: str) -> dict[str, dict[str, float | None]]: ...
