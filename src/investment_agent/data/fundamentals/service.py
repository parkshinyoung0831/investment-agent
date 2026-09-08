"""SEC CompanyFacts를 v1 공시·재무 원장에 적재하는 실행 경로.

`application/`에 두지 않는다. 이 도메인의 application은 port와 domain만 알고
어댑터를 모르는 것이 규칙인데(ARCHITECTURE.md, `test_architecture`가 검사한다),
이 파일은 `Database`를 만들어 저장소에 넘기는 배선이다.

이 모듈은 원천 접근과 정규화를 주입받는다. 따라서 data 패키지는 universe의
수집기를 직접 부르지 않고, 진입점이 identity gate에서 얻은 CIK만 넘긴다.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from investment_agent.data.fundamentals.domain.filings import Filing, FilingRef, is_periodic
from investment_agent.data.fundamentals.repository import FundamentalsRepository
from investment_agent.data.universe.domain.identifiers import normalize_cik
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

COMPANY_MAPPING_VERSION = "v1"

# db/postgres/v1/30_fundamentals.sql의 financials 수치 계약. 원천 변환의 보조
# provenance(source_manifest·filed_at)는 검증에만 쓰며 wide 표에 흘려 보내지 않는다.
_FINANCIAL_COLUMNS = frozenset({
    "cik", "period_end", "accession_no", "fiscal_year", "fiscal_period",
    "revenue", "cost_of_goods_and_services_sold", "gross_profit",
    "research_and_development_expenses", "selling_general_and_admin_expenses",
    "operating_income_loss", "interest_expense", "pretax_income_loss", "income_taxes",
    "net_income", "minority_interest_income", "net_income_to_common_shareholders",
    "eps_basic_gaap", "eps_diluted_gaap", "dividends_declared_per_share", "assets",
    "current_assets_total", "cash_and_cash_equivalents", "short_term_investments",
    "trade_receivables", "inventories", "property_plant_equipment_net", "goodwill",
    "intangible_assets_excluding_goodwill", "operating_lease_right_of_use_asset",
    "liabilities", "is_liabilities_derived", "current_liabilities_total", "trade_payables",
    "short_term_debt", "current_portion_of_long_term_debt", "long_term_debt",
    "total_debt_including_current", "operating_lease_current_debt_equivalent",
    "operating_lease_non_current_debt_equivalent", "common_equity", "common_equity_scope",
    "minority_interest_balance", "mezzanine_equity", "preferred_stock", "retained_earnings",
    "net_cash_from_operating_activities", "net_cash_from_investing_activities",
    "net_cash_from_financing_activities", "depreciation_amortization_cf",
    "stock_based_compensation_cf", "capital_expenses", "acquisitions_net_of_cash",
    "stock_repurchase_payments", "common_dividends_paid", "long_term_debt_issued",
    "long_term_debt_repaid", "shares_average", "shares_fully_diluted_average",
    "net_interest_income", "provision_for_credit_losses", "net_loans_and_leases",
    "total_deposits", "mapping_version",
})
_REQUIRED_FINANCIAL_COLUMNS = frozenset({
    "cik", "period_end", "accession_no", "fiscal_year", "fiscal_period", "mapping_version",
})

FilingSource = Callable[[int, date], Sequence[FilingRef]]
CompanyFactsSource = Callable[[int], Mapping[str, Any]]
FactsNormalizer = Callable[..., list[dict[str, Any]]]
WideBuilder = Callable[[list[dict[str, Any]]], Any]


@dataclass(frozen=True)
class FundamentalsRefreshResult:
    ciks: int
    filings_discovered: int
    filings_written: int
    filings_parsed: int
    filings_empty: int
    filings_unsupported: int
    financial_rows: int
    failures: tuple[dict[str, str], ...]


def _to_filing(ref: FilingRef, cik: str) -> Filing:
    """원천 공시 참조를 저장 계약으로 변환하며 CIK 혼입을 거부한다."""
    source_cik = normalize_cik(ref.cik) if ref.cik is not None else cik
    if source_cik != cik:
        raise ValueError(f"filing {ref.accession_no}: source CIK {source_cik} differs from {cik}")
    return Filing.from_row({
        "accession_no": ref.accession_no,
        "cik": cik,
        "form_type": ref.form_type,
        "filing_date": ref.filing_date,
        "report_date": ref.report_date,
        "source": ref.source or "sec_edgar",
    })


def _financial_row(row: Mapping[str, Any], *, mapping_version: str) -> dict[str, Any]:
    persisted = {key: value for key, value in row.items() if key in _FINANCIAL_COLUMNS}
    persisted["mapping_version"] = mapping_version
    missing = sorted(_REQUIRED_FINANCIAL_COLUMNS - set(persisted))
    if missing:
        raise ValueError(f"wide financial row misses required columns: {missing}")
    if persisted["fiscal_period"] not in {"Q1", "Q2", "Q3", "Q4"}:
        raise ValueError(f"wide financial row has unsupported fiscal_period: {persisted['fiscal_period']!r}")
    return persisted


def refresh_fundamentals(
    db: Database,
    *,
    ciks: Sequence[str],
    floor: date,
    filing_source: FilingSource,
    companyfacts_source: CompanyFactsSource,
    facts_normalizer: FactsNormalizer,
    wide_builder: WideBuilder,
    mapping_version: str = COMPANY_MAPPING_VERSION,
) -> FundamentalsRefreshResult:
    """발견→공시 원장→CompanyFacts 정규화→wide 적재를 CIK별로 끝낸다.

    한 CIK가 실패해도 이미 검증된 다른 CIK는 보존한다. 실패한 공시는 processing
    장부에 완료로 기록하지 않으므로 다음 실행에서 다시 시도한다.
    """
    normalized_ciks = sorted({cik for value in ciks if (cik := normalize_cik(value))})
    repo = FundamentalsRepository(db)
    counts: Counter[str] = Counter()
    failures: list[dict[str, str]] = []

    for cik in normalized_ciks:
        cik_number = int(cik)
        try:
            discovered = [
                _to_filing(ref, cik)
                for ref in filing_source(cik_number, floor)
                if is_periodic(ref.form_type)
            ]
            discovered_by_accession = {filing.accession_no: filing for filing in discovered}
            filings = list(discovered_by_accession.values())
            counts["filings_discovered"] += len(filings)
            counts["filings_written"] += repo.upsert_filings(filings)
            if not filings:
                continue

            pending = set(repo.unprocessed_accessions(
                content_type="company", mapping_version=mapping_version, ciks=[cik]
            )) & set(discovered_by_accession)
            if not pending:
                continue

            facts = facts_normalizer(
                companyfacts_source(cik_number),
                filings=filings,
                target_accessions=pending,
                floor=floor,
                allow_filing_fallback=True,
            )
            fact_counts = Counter(str(row.get("accession_no") or "") for row in facts)
            batch = wide_builder(facts)
            rows_by_accession: Counter[str] = Counter()
            rows: list[dict[str, Any]] = []
            for row in batch.core_rows:
                accession_no = str(row.get("accession_no") or "")
                if accession_no not in pending:
                    continue
                persisted = _financial_row(row, mapping_version=mapping_version)
                if persisted["cik"] != cik:
                    raise ValueError(f"financial row CIK {persisted['cik']!r} differs from {cik}")
                rows.append(persisted)
                rows_by_accession[accession_no] += 1
            counts["financial_rows"] += repo.upsert_financials(rows)

            for accession_no in sorted(pending):
                facts_count = fact_counts[accession_no]
                rows_count = rows_by_accession[accession_no]
                status = "parsed" if rows_count else ("unsupported" if facts_count else "empty")
                repo.record_processing(
                    accession_no=accession_no,
                    content_type="company",
                    mapping_version=mapping_version,
                    status=status,
                    facts_count=facts_count,
                    rows_count=rows_count,
                )
                counts[f"filings_{status}"] += 1
        except Exception as exc:  # noqa: BLE001 - 개별 CIK 실패는 재시도 가능하게 남긴다
            log.exception("fundamentals refresh failed cik=%s", cik)
            failures.append({"cik": cik, "error": repr(exc)})

    result = FundamentalsRefreshResult(
        ciks=len(normalized_ciks),
        filings_discovered=counts["filings_discovered"],
        filings_written=counts["filings_written"],
        filings_parsed=counts["filings_parsed"],
        filings_empty=counts["filings_empty"],
        filings_unsupported=counts["filings_unsupported"],
        financial_rows=counts["financial_rows"],
        failures=tuple(failures),
    )
    log.info("fundamentals_refresh %s", result)
    return result


__all__ = ["COMPANY_MAPPING_VERSION", "FundamentalsRefreshResult", "refresh_fundamentals"]
