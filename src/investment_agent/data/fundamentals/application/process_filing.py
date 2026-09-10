"""공시 한 건의 기업 전체·세그먼트 결과를 처리한다."""
from __future__ import annotations

from datetime import date
from typing import Any

from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import network_retry
from investment_agent.data.fundamentals.domain.normalization import (
    build_company_financials,
)
from investment_agent.data.fundamentals.domain.filings import filing_row
from investment_agent.data.fundamentals.application.segment_metrics import (
    build_segment_metrics,
)
from investment_agent.data.fundamentals.application import (
    CompanyFinancialRepository,
    SegmentFilingSource,
    SegmentMetricRepository,
)
from investment_agent.data.fundamentals.domain.services.segment_periods import (
    belongs_to_report_period,
)

log = get_logger(__name__)


@network_retry(attempts=3, max_wait=5)
def process_company_facts(
    facts: list[dict],
    *,
    repository: CompanyFinancialRepository,
    filings: list | None = None,
    cik: object | None = None,
) -> dict[str, Any]:
    """표준 fact를 기업 전체 재무로 만들고 저장한다."""
    batch = build_company_financials(facts)
    rows_by_accession: dict[str, int] = {}
    for row in batch.core_rows:
        accession_no = str(row.get("accession_no") or "")
        if accession_no:
            rows_by_accession[accession_no] = rows_by_accession.get(accession_no, 0) + 1
    if filings:
        if cik is None:
            raise ValueError("cik is required when filing references are persisted")
        upsert_filings = getattr(repository, "upsert_filings", None)
        if upsert_filings is None:
            raise TypeError("company repository must expose upsert_filings before financial writes")
        upsert_filings([filing_row(filing, cik) for filing in filings])
    core_count = repository.upsert_core_wide(batch.core_rows)
    quarantine_count = repository.report_anomalies(batch.quarantine_rows)
    return {
        "rows": core_count,
        "core_rows": core_count,
        "quarantined": quarantine_count,
        "rows_by_accession": rows_by_accession,
    }


def segment_forms(period_kind: str) -> tuple[str, str]:
    """세그먼트 기간 종류에 대응하는 SEC form을 반환한다."""
    if period_kind == "quarter":
        return "10-Q", "10-Q/A"
    if period_kind == "annual":
        return "10-K", "10-K/A"
    raise ValueError(f"unsupported segment period kind: {period_kind}")


def current_segment_facts(
    facts: list[dict],
    *,
    filing: dict,
    period_kind: str,
    fiscal_year: int | None,
    fiscal_period: str | None,
) -> list[dict]:
    """공시의 현재 보고기간 fact만 남기고 표준 회계기간 키를 부여한다."""
    try:
        report_end = date.fromisoformat(str(filing["report_date"])[:10])
    except (KeyError, TypeError, ValueError):
        return []

    allowed_kinds = {period_kind, "instant"}
    if period_kind == "quarter":
        allowed_kinds.add("ytd")

    selected: list[dict] = []
    for fact in facts:
        try:
            period_end = date.fromisoformat(str(fact["period_end"])[:10])
        except (KeyError, TypeError, ValueError):
            continue
        fact_kind = str(fact.get("period_kind") or "")
        if fact_kind not in allowed_kinds:
            continue
        if not belongs_to_report_period(
            period_end,
            report_end,
            is_instant=fact_kind == "instant",
        ):
            continue
        row = dict(fact)
        if fiscal_year is not None and fiscal_period is not None:
            row["fiscal_year"] = fiscal_year
            row["fiscal_period"] = fiscal_period
            row["period_key"] = f"{fiscal_year}{fiscal_period}"
        selected.append(row)
    return selected


def segment_filing_row(
    *,
    cik: str,
    filing: dict,
    facts_count: int,
    segment_rows_count: int,
    status: str | None = None,
    source: str = "daily_xbrl",
) -> dict:
    """세그먼트 공시 처리 상태를 저장소 행으로 만든다."""
    from investment_agent.data.fundamentals.domain.taxonomy.segment_axes import SEGMENT_MAPPING_VERSION

    return {
        "cik": str(cik).zfill(10),
        "accession_no": filing["accession_no"],
        "form_type": filing["form_type"],
        "filing_date": filing.get("accepted_date") or filing["filing_date"],
        "report_date": filing["report_date"],
        "status": status or (
            "parsed" if segment_rows_count else "unsupported" if facts_count else "empty"
        ),
        "mapping_version": SEGMENT_MAPPING_VERSION,
        "source": source,
        "facts_count": facts_count,
        "rows_count": segment_rows_count,
    }


def process_segment_cik(
    *,
    cik: int,
    forms: tuple[str, str],
    filed_cutoff: date,
    existing: dict[str, set[str]],
    period_kind: str,
    axis_registry: dict[str, dict] | None = None,
    concept_registry: dict[str, Any] | None = None,
    source: SegmentFilingSource,
) -> dict:
    """CIK 한 건의 새 공시 문서를 파싱해 저장 전 결과를 만든다."""
    from investment_agent.data.fundamentals.domain.services.parse_xbrl import (
        parse_fiscal_focus,
        parse_segment_facts,
    )
    filings = source.filings_filed_since(
        cik,
        forms=forms,
        cutoff=filed_cutoff,
    )
    pending = [
        filing
        for filing in filings
        if filing["accession_no"] not in existing.get(f"{cik:010d}", set())
    ]
    filing_rows: list[dict] = []
    metric_rows: list[dict] = []
    ytd_rows: list[dict] = []
    missing_documents: list[str] = []
    failures: list[dict] = []
    unmapped_concepts: set[str] = set()

    for filing in pending:
        try:
            document = source.fetch_xbrl_document(
                cik,
                filing["accession_no"],
                filing.get("primary_document"),
            )
            if document is None:
                reason = "XBRL document is missing"
                missing_documents.append(filing["accession_no"])
                failures.append({
                    "cik": cik,
                    "accession_no": filing["accession_no"],
                    "error": reason,
                })
                continue

            fiscal_year, fiscal_period = parse_fiscal_focus(document)
            if period_kind == "annual":
                fiscal_period = "FY"
            facts = current_segment_facts(
                parse_segment_facts(document, axis_registry),
                filing=filing,
                period_kind=period_kind,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
            )
            built = build_segment_metrics(
                f"{cik:010d}",
                filing,
                facts,
                period_kind,
                concept_registry,
            )
            metric_rows.extend(built.metric_rows)
            ytd_rows.extend(built.ytd_rows)
            unmapped_concepts.update(built.unmapped_concepts)
            filing_rows.append(
                segment_filing_row(
                    cik=f"{cik:010d}",
                    filing=filing,
                    facts_count=len(facts),
                    segment_rows_count=len(built.metric_rows),
                )
            )
        except Exception as exc:  # noqa: BLE001 - 다음 accession_no 처리를 계속한다
            log.error(
                "segments filing failed CIK=%s accession_no=%s error=%r",
                cik,
                filing.get("accession_no"),
                exc,
            )
            failures.append({
                "cik": cik,
                "accession_no": filing.get("accession_no"),
                "error": repr(exc),
            })

    return {
        "cik": cik,
        "filings_discovered": len(filings),
        "skipped_existing": len(filings) - len(pending),
        "filing_rows": filing_rows,
        "wide_rows": metric_rows,
        "ytd_rows": ytd_rows,
        "missing_documents": missing_documents,
        "failures": failures,
        "unmapped_concepts": sorted(unmapped_concepts),
    }


def derive_segment_rows(
    pairs: set[tuple[str, int]],
    ytd_rows: list[dict],
    *,
    replace: set[tuple[str, str]] | None = None,
    replacement_rows: list[dict] | None = None,
    repository: SegmentMetricRepository,
) -> list[dict]:
    """저장된 연도 지표와 이번 YTD 관측값으로 discrete 분기를 계산한다."""
    if not pairs:
        return []
    from investment_agent.data.fundamentals.domain.services.build_segment_metrics import (
        derive_q4_rows,
        derive_ytd_quarters,
    )
    rows = repository.fetch_metric_years(pairs)
    if replace:
        rows = [
            row
            for row in rows
            if (str(row["cik"]), str(row["accession_no"])) not in replace
        ]
        rows.extend(
            repository.hydrate_metric_rows(
                row
                for row in (replacement_rows or [])
                if (str(row["cik"]), str(row["accession_no"])) in replace
            )
        )

    grouped: dict[tuple[str, int, str], list[dict]] = {}
    for row in rows:
        key = (
            str(row["cik"]),
            int(row["fiscal_year"]),
            str(row["fiscal_period"]),
        )
        grouped.setdefault(key, []).append(row)

    derived: list[dict] = []
    for cik, year in sorted(pairs):
        derived.extend(
            derive_q4_rows(
                grouped.get((cik, year, "FY"), []),
                grouped.get((cik, year, "Q1"), []),
                grouped.get((cik, year, "Q2"), []),
                grouped.get((cik, year, "Q3"), []),
            )
        )
    derived.extend(derive_ytd_quarters(ytd_rows, grouped))
    return derived


def persist_segment_filings(
    filing_rows: list[dict],
    metric_rows: list[dict],
    ytd_rows: list[dict] | None = None,
    *,
    replace: set[tuple[str, str]] | None = None,
    repository: SegmentMetricRepository,
) -> dict[str, int]:
    """direct·derived 지표가 모두 성공한 뒤 공시를 완료 상태로 전환한다."""
    ytd_rows = ytd_rows or []
    # segment_metrics와 filing_processing 모두 filings.accession_no를 참조한다.
    # 자식 행을 먼저 쓰면 빈 DB에서 FK 위반으로 전체 공시가 유실되므로 부모
    # 원장을 먼저 만들고, 그 다음 지표와 처리 상태를 적재한다.
    filing_count = repository.upsert_filings(filing_rows)
    pairs = {
        (str(row["cik"]), int(row["fiscal_year"]))
        for row in (*metric_rows, *ytd_rows)
    }
    if replace:
        direct_count, persisted_direct = repository.upsert_segment_metrics_with_rows(
            metric_rows
        )
        derived_rows = derive_segment_rows(
            pairs,
            ytd_rows,
            replace=replace,
            replacement_rows=persisted_direct,
            repository=repository,
        )
        derived_count, persisted_derived = repository.upsert_segment_metrics_with_rows(
            derived_rows
        )
        repository.delete_stale_metrics_for_accessions(
            replace,
            [*persisted_direct, *persisted_derived],
        )
    else:
        direct_count = repository.upsert_segment_metrics(metric_rows)
        derived_rows = derive_segment_rows(
            pairs,
            ytd_rows,
            repository=repository,
        )
        derived_count = repository.upsert_segment_metrics(derived_rows)
    return {
        "filings": filing_count,
        "wide_rows": direct_count + derived_count,
        "derived_q4_rows": derived_count,
    }
