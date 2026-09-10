"""기업 재무 이력을 명시적으로 백필한다.

기업 전체 재무는 daily와 같은 companyfacts 원천을 쓰고, 세그먼트는 차원 데이터가
companyfacts에 없어 SEC FSDS 분기 파일을 쓴다.
"""
from __future__ import annotations

import traceback
from datetime import date, datetime
from zoneinfo import ZoneInfo

from investment_agent.operations.backfill import resolve_backfill_window, select_accessions
from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.application.segment_metrics import build_segment_metrics
from investment_agent.data.fundamentals.application import (
    CompanyFilingSource,
    CompanyFinancialRepository,
    SegmentBulkFilingSource,
    SegmentMetricRepository,
)
from investment_agent.data.fundamentals.application.process_filing import (
    persist_segment_filings,
    process_company_facts,
    segment_forms,
)
from investment_agent.data.fundamentals.domain.taxonomy.financial_columns import COMPANYFACT_COLUMNS

log = get_logger(__name__)

_COMPANY_BACKFILL_YEARS = 10
_COMPANY_BACKFILL_SOURCE = "backfill_companyfacts"
# 세그먼트는 실적 카드의 13분기 추세와 축 비교가 주 용도라 3년(12분기)이면 덮는다.
# 기업 전체 재무(10년)보다 훨씬 짧게 잡는 이유는 용량이다 — 행이 400바이트로 무거워
# 5년 전량이면 41MB였다. 3년으로 줄이면 Supabase Free 500MB 한도에서 절반가량을 아낀다.
_SEGMENT_BACKFILL_YEARS = 3


def _company_backfill_targets(
    filings: list,
    *,
    cik: str,
    scope: str,
    processed: dict[str, set[str]],
) -> dict[str, object]:
    """한 SEC 등록인의 상태 원장을 기준으로 실제 백필 공시를 고른다."""
    targets: dict[str, object] = {}
    for filing in filings:
        if filing.accession_no in select_accessions(
            {filing.accession_no},
            scope=scope,
            completed=processed.get(cik, set()),
        ):
            targets[filing.accession_no] = filing
    return targets


def backfill_company_history(
    *,
    source: CompanyFilingSource,
    repository: CompanyFinancialRepository,
    backfill_from: str | None = None,
    scope: str = "gaps",
    target_tickers: set[str] | None = None,
) -> dict:
    """기업 전체 재무를 accession_no 상태에 따라 선별해 백필한다.

    daily와 같은 companyfacts 경로를 쓴다. 경로가 갈려 있으면 매핑 정책을 고쳐도
    최신 분기에만 반영되고 과거 이력은 낡은 정책으로 남는다 — 실제로 EPS 충전율이
    daily 95%, 백필 1.5%로 갈렸다.
    """
    floor = resolve_backfill_window(
        backfill_from,
        default_years=_COMPANY_BACKFILL_YEARS,
    ).start
    requested_tickers = {
        str(ticker).strip().upper()
        for ticker in (target_tickers or set())
        if str(ticker).strip()
    }
    current_ciks = (
        repository.ciks_for_tickers(requested_tickers)
        if requested_tickers
        else repository.tracked_ciks()
    )
    missing_ciks = (
        set(repository.ciks_missing_financials())
        if scope == "missing"
        else set()
    )
    if scope == "missing":
        current_ciks &= missing_ciks

    source_ciks = set(current_ciks)

    processed = repository.processed_filing_accessions()
    metrics = {
        "rows": 0,
        "core_rows": 0,
        "quarantined": 0,
        "companies": len(current_ciks),
        "ciks": 0,
        "filings_discovered": 0,
        "filings_selected": 0,
        "filings_completed": 0,
        "filings_empty": 0,
        "filings_superseded": 0,
        "rows_removed": 0,
        "failures": [],
        "scope": scope,
    }
    if not source_ciks:
        log.info("company history backfill target count is 0 scope=%s", scope)
        return metrics

    for cik_key in sorted(source_ciks):
        cik = int(cik_key)
        metrics["ciks"] += 1
        try:
            filings = source.all_financial_filings(cik, cutoff=floor)
        except Exception as exc:  # noqa: BLE001 - 다음 CIK는 계속한다
            reason = f"submission discovery failed for CIK {cik:010d}: {exc!r}"
            metrics["failures"].append(reason)
            log.error(reason)
            continue

        metrics["filings_discovered"] += len(filings)
        initial_targets = _company_backfill_targets(
            filings,
            cik=cik_key,
            scope=scope,
            processed=processed,
        )
        if not initial_targets:
            continue

        try:
            document = source.companyfacts(cik)
            same_cik_superseded = source.superseded_filing_accessions(
                document,
                filings,
            )
        except Exception as exc:  # noqa: BLE001 - 다음 CIK는 계속한다
            reason = f"companyfacts load failed for CIK {cik:010d}: {exc!r}"
            metrics["failures"].append(reason)
            log.error("%s\n%s", reason, traceback.format_exc())
            continue

        superseded_targets = [
            (filing, cik_key)
            for accession_no, filing in initial_targets.items()
            if accession_no in same_cik_superseded
        ]
        targets = {
            accession_no: filing
            for accession_no, filing in initial_targets.items()
            if accession_no not in same_cik_superseded
        }
        if superseded_targets:
            repository.mark_superseded_filing_targets(
                superseded_targets,
                source=_COMPANY_BACKFILL_SOURCE,
            )
            metrics["filings_superseded"] += len(superseded_targets)
            log.info(
                "predecessor filings superseded: cik=%010d targets=%d",
                cik,
                len(superseded_targets),
            )
        if not targets:
            continue

        metrics["filings_selected"] += len(targets)
        load_succeeded = True
        reason = ""
        try:
            facts = source.companyfacts_to_facts(
                document,
                filings=filings,
                target_accessions=set(targets),
                floor=floor,
                allowed_keys=COMPANYFACT_COLUMNS,
                allow_filing_fallback=True,
            )
        except Exception as exc:  # noqa: BLE001 - 다음 CIK는 계속한다
            facts = []
            load_succeeded = False
            reason = f"companyfacts load failed for CIK {cik:010d}: {exc!r}"
            metrics["failures"].append(reason)
            log.error("%s\n%s", reason, traceback.format_exc())

        loaded_accessions = {
            str(row.get("accession_no") or "")
            for row in facts
            if row.get("accession_no")
        }
        fact_counts: dict[str, int] = {}
        for row in facts:
            accession_no = str(row.get("accession_no") or "")
            if accession_no:
                fact_counts[accession_no] = fact_counts.get(accession_no, 0) + 1
        completed_targets = {
            accession_no: value
            for accession_no, value in targets.items()
            if accession_no in loaded_accessions
        }
        empty_targets = {
            accession_no: value
            for accession_no, value in targets.items()
            if accession_no not in loaded_accessions
        }

        if facts:
            try:
                loaded = process_company_facts(
                    facts,
                    filings=filings,
                    cik=cik_key,
                    repository=repository,
                )
                rows_by_accession = loaded["rows_by_accession"]
                parsed_targets = {
                    accession_no: value
                    for accession_no, value in completed_targets.items()
                    if rows_by_accession.get(accession_no, 0) > 0
                }
                empty_targets.update({
                    accession_no: value
                    for accession_no, value in completed_targets.items()
                    if rows_by_accession.get(accession_no, 0) == 0
                })
                for key in ("rows", "core_rows", "quarantined"):
                    metrics[key] += loaded[key]
                repository.mark_processed_filing_targets(
                    [
                        (
                            filing,
                            cik_key,
                            fact_counts[accession_no],
                            rows_by_accession[accession_no],
                        )
                        for accession_no, filing in parsed_targets.items()
                    ],
                    source=_COMPANY_BACKFILL_SOURCE,
                )
                metrics["filings_completed"] += len(parsed_targets)
            except Exception as exc:  # noqa: BLE001 - 다음 CIK는 계속한다
                reason = f"backfill load failed: {exc!r}"
                metrics["failures"].append(reason)
                load_succeeded = False
                log.error(reason)

        if load_succeeded and empty_targets:
            repository.mark_empty_filing_targets(
                [(filing, cik_key) for filing in empty_targets.values()],
                source=_COMPANY_BACKFILL_SOURCE,
            )
            metrics["filings_empty"] += len(empty_targets)

        if load_succeeded and scope == "all":
            try:
                report_dates = [
                    str(filing.report_date)
                    for filing in filings
                    if filing.report_date
                    and filing.accession_no not in same_cik_superseded
                ]
                if report_dates:
                    metrics["rows_removed"] += repository.reconcile_wide_history(
                        {cik_key: max(report_dates)},
                        floor,
                    )
            except Exception as exc:  # noqa: BLE001 - 다음 CIK는 계속한다
                reason = f"backfill reconciliation failed: {exc!r}"
                metrics["failures"].append(reason)
                log.error(reason)

    # 대상 CIK가 있는데 공시를 하나도 못 찾았으면 원천 계약이 깨진 것이다.
    # 이걸 성공으로 넘기면 표를 비우고 돌린 재적재가 "0건 성공"으로 끝나 버린다.
    if not metrics["filings_discovered"]:
        reason = (
            f"backfill discovered no filings for {metrics['ciks']} CIKs "
            f"(scope={scope}, floor={floor.isoformat()}); "
            "SEC submissions 응답과 EDGAR_USER_AGENT를 확인하라"
        )
        metrics["failures"].append(reason)
        log.error(reason)

    return metrics


def _completed_segment_accessions(
    ciks: set[str],
    completed: dict[str, set[str]],
) -> set[str]:
    """선택 CIK에서 완료된 전역 고유 accession_no 집합."""
    return set().union(*(completed.get(cik, set()) for cik in ciks)) if ciks else set()


def _segment_retention_cutoff(*, today: date | None = None) -> date:
    market_today = today or datetime.now(ZoneInfo("America/New_York")).date()
    return resolve_backfill_window(
        None,
        default_years=_SEGMENT_BACKFILL_YEARS,
        today=market_today,
    ).start


def _segment_backfill_cutoff(
    backfill_from: str | None,
    *,
    today: date | None = None,
) -> date:
    """요청 구간을 보존 창 안으로 제한해 적재 직후 삭제되는 재처리를 막는다."""
    retention_cutoff = _segment_retention_cutoff(today=today)
    if not backfill_from:
        return retention_cutoff
    requested_cutoff = resolve_backfill_window(backfill_from).start
    return max(requested_cutoff, retention_cutoff)


def _yyyymmdd(value: int | str) -> str:
    text = str(value).zfill(8)
    return date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()


def backfill_segment_history(
    period_kind: str,
    *,
    source: SegmentBulkFilingSource,
    repository: SegmentMetricRepository,
    backfill_from: str | None = None,
    scope: str = "gaps",
    target_tickers: set[str] | None = None,
) -> dict:
    """세그먼트 FSDS 분기 파일을 원본 파일 단위로 한 번씩 처리한다."""
    from investment_agent.data.fundamentals.domain.services.normalize_segment_facts import (
        bulk_frames_to_filings_and_facts,
    )
    cutoff = _segment_backfill_cutoff(backfill_from)
    tracked_ciks = repository.tracked_ciks()
    requested_tickers = {
        str(ticker).strip().upper()
        for ticker in (target_tickers or set())
        if str(ticker).strip()
    }
    current_ciks = (
        repository.ciks_for_tickers(requested_tickers)
        if requested_tickers
        else set(tracked_ciks)
    )
    forms = segment_forms(period_kind)
    existing = repository.existing_accessions(forms)
    if scope == "missing":
        missing = repository.ciks_missing_segments(period_kind)
        # 지표가 0행이어도 현재 매핑 버전에서 empty/unsupported로 완료한 종목은
        # 수집 누락이 아니다. 다시 넣으면 매 실행마다 같은 parquet를 읽게 된다.
        missing -= set(existing)
        current_ciks &= missing
    source_ciks = set(current_ciks)
    skip_accessions = (
        _completed_segment_accessions(source_ciks, existing)
        if scope in {"gaps", "missing"}
        else set()
    )

    metrics = {
        "wide_rows": 0,
        "derived_q4_rows": 0,
        "filings": 0,
        "companies": len(current_ciks),
        "ciks_processed": len(source_ciks),
        "batches": 0,
        "existing_accessions": sum(
            len(existing.get(cik, set())) for cik in source_ciks
        ),
        "source_accessions_skipped": len(skip_accessions),
        "reports_discovered": 0,
        "failures": [],
        "unmapped_concepts": set(),
        "scope": scope,
    }
    if not source_ciks:
        log.info(
            "segments history backfill target count is 0 period=%s scope=%s",
            period_kind,
            scope,
        )
        return metrics

    source.ensure_data(cutoff=cutoff)

    for batch, frames in source.iter_batches(
        ciks={int(cik) for cik in source_ciks},
        forms=forms,
        cutoff=cutoff,
        skip_accessions=skip_accessions,
        include_accessions=None,
    ):
        metrics["batches"] += 1
        metrics["reports_discovered"] += len(batch.reports)
        try:
            filing_rows, facts_by_accession, batch_unmapped = (
                bulk_frames_to_filings_and_facts(
                    frames,
                    ciks={int(cik) for cik in source_ciks},
                    period_kind=period_kind,
                )
            )
            metrics["unmapped_concepts"].update(batch_unmapped)
            filing_by_key = {
                (row["cik"], row["accession_no"]): row for row in filing_rows
            }
            metric_rows: list[dict] = []
            for report in batch.reports:
                facts = facts_by_accession.get(report.accession_no, [])
                filing = {
                    "accession_no": report.accession_no,
                    "form_type": report.form_type,
                    "report_date": _yyyymmdd(report.period),
                    "accepted_date": _yyyymmdd(report.filed),
                }
                report_rows: list[dict] = []
                cik_key = f"{int(report.cik):010d}"
                selected = report.accession_no in select_accessions(
                    {report.accession_no},
                    scope=scope,
                    completed=existing.get(cik_key, set()),
                )
                if selected:
                    built = build_segment_metrics(
                        cik_key,
                        filing,
                        facts,
                        period_kind,
                    )
                    metrics["unmapped_concepts"].update(built.unmapped_concepts)
                    report_rows.extend(built.metric_rows)
                    state = filing_by_key.get((cik_key, report.accession_no))
                    if state is not None:
                        state["rows_count"] = len(built.metric_rows)
                        state["status"] = (
                            "parsed"
                            if built.metric_rows
                            else "unsupported"
                            if state.get("facts_count")
                            else "empty"
                        )
                metric_rows.extend(report_rows)

            selected_states = [
                row
                for (cik, accession_no), row in filing_by_key.items()
                if accession_no
                in select_accessions(
                    {accession_no},
                    scope=scope,
                    completed=existing.get(cik, set()),
                )
            ]
            replace = {
                (str(row["cik"]), str(row["accession_no"]))
                for row in selected_states
            }
            persisted = persist_segment_filings(
                selected_states,
                metric_rows,
                replace=replace,
                repository=repository,
            )
            for key in ("filings", "wide_rows", "derived_q4_rows"):
                metrics[key] += persisted[key]
            for row in selected_states:
                if row["status"] in {"parsed", "empty", "unsupported"}:
                    existing.setdefault(row["cik"], set()).add(row["accession_no"])
            log.info(
                "segments backfill committed source=%s filings=%d wide_rows=%d",
                batch.source_file,
                persisted["filings"],
                persisted["wide_rows"],
            )
        except Exception as exc:  # noqa: BLE001 - 앞선 batch commit은 보존한다
            log.error(
                "segments backfill source=%s failed: %s\n%s",
                batch.source_file,
                exc,
                traceback.format_exc(),
            )
            metrics["failures"].append({
                "source_file": batch.source_file,
                "error": repr(exc),
            })
    if source_ciks and scope in {"all", "missing"} and not metrics["reports_discovered"]:
        metrics["failures"].append({
            "source_file": None,
            "error": (
                "segment backfill discovered no reports for "
                f"{len(source_ciks)} tracked CIKs (period={period_kind}, "
                f"scope={scope}, cutoff={cutoff.isoformat()})"
            ),
        })
    return metrics


def prune_segment_history(
    repository: SegmentMetricRepository,
    *,
    today: date | None = None,
) -> dict[str, int]:
    """정책 보존 기간보다 오래된 세그먼트 지표와 처리 상태를 제거한다."""
    cutoff = _segment_retention_cutoff(today=today).isoformat()
    deleted = repository.delete_history_before(cutoff)
    log.info("segments retention cutoff=%s deleted=%s", cutoff, deleted)
    return deleted

