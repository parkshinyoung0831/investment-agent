"""SEC 공시 원천 포트."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any, Protocol


class CompanyFilingSource(Protocol):
    """기업 전체 재무 공시 탐색과 Company Facts 원천."""

    def recent_financial_ciks(
        self,
        *,
        tracked_ciks: set[int],
        end: date,
        lookback_days: int,
    ) -> tuple[set[int], int]: ...

    def submissions(self, cik: str | int) -> dict[str, Any]: ...

    def financial_filings(self, document: dict[str, Any]) -> list[Any]: ...

    def pending_filings(
        self,
        filings: list[Any],
        last_filed: str | None,
        processed_accessions: set[str] | None = None,
    ) -> list[Any]: ...

    def all_financial_filings(self, cik: str | int, *, cutoff: date) -> list[Any]: ...

    def companyfacts(self, cik: str | int) -> dict[str, Any]: ...

    def filing_focus(
        self,
        document: dict[str, Any],
        filings: list[Any],
    ) -> dict[str, tuple[int, str]]: ...

    def superseded_filing_accessions(
        self,
        document: dict[str, Any],
        filings: list[Any],
    ) -> set[str]: ...

    def companyfacts_to_facts(self, document: dict[str, Any], **kwargs: Any) -> list[dict]: ...


class SegmentFilingSource(Protocol):
    """세그먼트 XBRL 공시 탐색과 instance 문서 원천."""

    def recent_filing_ciks(
        self,
        *,
        tracked_ciks: set[int],
        forms: Iterable[str],
        end: date,
        lookback_days: int,
    ) -> tuple[set[int], int]: ...

    def filings_filed_since(
        self,
        cik: str | int,
        *,
        forms: Iterable[str],
        cutoff: date,
    ) -> list[dict]: ...

    def fetch_xbrl_document(
        self,
        cik: str | int,
        accession_no: str,
        primary_document: str | None = None,
    ) -> bytes | None: ...


class SegmentBulkFilingSource(Protocol):
    """세그먼트 재무용 SEC FSDS 원천."""

    def ensure_data(self, *, cutoff: date | None = None) -> None: ...

    def iter_batches(
        self,
        *,
        ciks: Iterable[int],
        forms: Iterable[str],
        cutoff: date,
        skip_accessions: set[str],
        include_accessions: set[str] | None = None,
    ) -> Iterable[tuple[Any, Any]]: ...


class EarningsFilingSource(Protocol):
    """Item 2.02 실적 발표 공시 원천."""

    def earnings_8k_filings(
        self,
        cik: str | int,
        *,
        cutoff: date,
    ) -> list[Any]: ...

