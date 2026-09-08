"""표준 공시 fact에서 기업 전체 재무 결과를 만든다."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CompanyFinancialBatch:
    """한 번에 원자적으로 저장할 기업 전체 재무 결과."""

    core_rows: list[dict]
    quarantine_rows: list[dict]

    @property
    def row_count(self) -> int:
        return len(self.core_rows)


def build_company_financials(facts: list[dict]) -> CompanyFinancialBatch:
    """fact 선택·기간 파생·wide 생성·검증을 한 번만 수행한다."""
    from investment_agent.data.fundamentals.domain.services.reported_observations import to_wide_tables
    from investment_agent.data.fundamentals.domain.services.validate_financial_statements import (
        check_core_wide,
    )

    core_rows, mapping_issues = to_wide_tables(facts)
    valid_core_rows, validation_issues = check_core_wide(core_rows)
    return CompanyFinancialBatch(
        core_rows=valid_core_rows,
        quarantine_rows=[*mapping_issues, *validation_issues],
    )
