"""gurus 테스트용 FilingRecord/Position 팩토리. 외부 의존성 없음."""
from __future__ import annotations

from datetime import date

from investment_agent.data.institutional.domain.models import FilingRecord, Position


def make_position(
    *,
    source_row_no: int = 1,
    cusip: str = "037833100",
    issuer_name: str = "Apple Inc",
    value_usd: int = 1_000_000,
    quantity: int = 100,
    quantity_type: str = "SH",
    position_kind: str = "SHARES",
) -> Position:
    return Position(
        source_row_no=source_row_no,
        issuer_name=issuer_name,
        cusip=cusip,
        identifier_type="CINS" if cusip[0].isalpha() else "CUSIP",
        title_of_class="COM",
        value_usd=value_usd,
        quantity=quantity,
        quantity_type=quantity_type,
        position_kind=position_kind,
        investment_discretion="SOLE",
        other_manager=None,
        voting_sole=quantity,
        voting_shared=0,
        voting_none=0,
    )


def make_filing_record(
    *,
    accession_no: str = "0000950123-24-008740",
    manager_cik: str = "0001067983",
    positions: tuple[Position, ...] | None = None,
    form_type: str = "13F-HR",
    report_type: str = "13F HOLDINGS REPORT",
    parsed_line_count: int | None = None,
    reported_line_count: int | None = None,
) -> FilingRecord:
    """edgar.py가 만들어내는 것과 동일한 형태의 검증 통과용 레코드."""
    if positions is None:
        positions = (make_position(),)
    reported_value = sum(p.value_usd for p in positions)
    return FilingRecord(
        accession_no=accession_no,
        manager_cik=manager_cik,
        period_end=date(2024, 3, 31),
        form_type=form_type,
        report_type=report_type,
        filing_date=date(2024, 5, 15),
        accepted_at="2024-05-15T16:30:00",
        amendment_type=None,
        amendment_no=None,
        reported_value_usd=reported_value,
        reported_line_count=(
            len(positions) if reported_line_count is None else reported_line_count
        ),
        confidential_omitted=False,
        source_url="https://www.sec.gov/cgi-bin/browse-edgar",
        content_sha256="0" * 64,
        positions=positions,
        parsed_line_count=(
            len(positions) if parsed_line_count is None else parsed_line_count
        ),
    )
