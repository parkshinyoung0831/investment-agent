"""13F 수집·저장 경계에서 사용하는 명시적 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class RawPosition:
    """SEC Information Table 원본 행의 분석·감사 필수 필드."""

    issuer_name: str
    cusip: str
    reported_value: int
    quantity: int
    quantity_type: str
    position_kind: str
    source_row_no: int = 0
    identifier_type: str = "CUSIP"
    title_of_class: str | None = None
    investment_discretion: str | None = None
    other_manager: str | None = None
    voting_sole: int | None = None
    voting_shared: int | None = None
    voting_none: int | None = None


@dataclass(frozen=True)
class Position:
    """SEC 원본 한 행을 USD로 정규화한 DB 저장 단위.

    Combination Report의 중복 보유를 Python에서 먼저 합치면 sub-manager와
    voting 정보가 사라진다. 따라서 원본 행을 보존하고 effective View가 분석
    키별 합계를 만든다.
    """

    source_row_no: int
    issuer_name: str
    cusip: str
    identifier_type: str
    title_of_class: str | None
    value_usd: int
    quantity: int
    quantity_type: str
    position_kind: str
    investment_discretion: str | None
    other_manager: str | None
    voting_sole: int | None
    voting_shared: int | None
    voting_none: int | None

    def as_dict(self) -> dict:
        return {
            "source_row_no": self.source_row_no,
            "issuer_name": self.issuer_name,
            "cusip": self.cusip,
            "identifier_type": self.identifier_type,
            "title_of_class": self.title_of_class,
            "value_usd": self.value_usd,
            "quantity": self.quantity,
            "quantity_type": self.quantity_type,
            "position_kind": self.position_kind,
            "investment_discretion": self.investment_discretion,
            "other_manager": self.other_manager,
            "voting_sole": self.voting_sole,
            "voting_shared": self.voting_shared,
            "voting_none": self.voting_none,
        }


@dataclass(frozen=True)
class FilingRecord:
    """검증을 마친 13F 공시와 합산 포지션 묶음."""

    accession_no: str
    manager_cik: str
    period_end: date
    form_type: str
    report_type: str | None
    filing_date: date
    accepted_at: str | None
    amendment_type: str | None
    amendment_no: int | None
    reported_value_usd: int
    reported_line_count: int
    confidential_omitted: bool | None
    source_url: str
    content_sha256: str
    positions: tuple[Position, ...]
    # informationTable의 원시 infoTable 행 수. positions도 원시 행을 보존하지만
    # downstream View는 분석 키별로 합산하므로 SEC 요약 대조는 이 값으로 한다.
    parsed_line_count: int = 0

    def filing_payload(self) -> dict:
        return {
            "accession_no": self.accession_no,
            "manager_cik": self.manager_cik,
            "period_end": self.period_end.isoformat(),
            "form_type": self.form_type,
            "report_type": self.report_type,
            "filing_date": self.filing_date.isoformat(),
            "accepted_at": self.accepted_at,
            "amendment_type": self.amendment_type,
            "amendment_no": self.amendment_no,
            "reported_value_usd": self.reported_value_usd,
            "reported_line_count": self.reported_line_count,
            "confidential_omitted": self.confidential_omitted,
            "source_url": self.source_url,
            "content_sha256": self.content_sha256,
        }

    def positions_payload(self) -> list[dict]:
        """RPC에 넘기는 원천 포지션 배열. DB 컬럼 계약과 1:1로 맞춘다."""
        return [position.as_dict() for position in self.positions]
