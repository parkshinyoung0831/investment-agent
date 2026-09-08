"""최근 SEC 공시를 발견해 기업 전체·세그먼트 재무를 증분 동기화한다."""
from __future__ import annotations

import os
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from investment_agent.operations.backfill import resolve_backfill_window
from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.application import (
    CompanyFilingSource,
    CompanyFinancialRepository,
    SegmentFilingSource,
    SegmentMetricRepository,
)
from investment_agent.data.fundamentals.application.process_filing import (
    persist_segment_filings,
    process_company_facts,
    process_segment_cik,
    segment_forms,
)
from investment_agent.data.fundamentals.domain.taxonomy.financial_columns import COMPANYFACT_COLUMNS

log = get_logger(__name__)

_DEFAULT_LOOKBACK_DAYS = 7
_MAX_SEGMENT_WORKERS = 4
_REPROCESS_SOURCES = ("daily_xbrl",)
_COMPANY_BACKFILL_YEARS = 10


def sync_company_filings(
    *,
    source: CompanyFilingSource,
    repository: CompanyFinancialRepository,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    watchlist_only: bool = False,
    target_tickers: set[str] | None = None,
    earnings_event_detector: Callable[[str, str], dict] | None = None,
) -> dict:
    """최근 10-Q/10-K를 찾아 기업 전체 wide 재무를 갱신한다."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")

    metrics: dict = {
        "rows": 0,
        "core_rows": 0,
        "quarantined": 0,
        "ciks": 0,
        "ciks_scanned": 0,
        "ciks_indexed": 0,
        "index_files": 0,
        "filings": 0,
        "earnings_events": 0,
        "failures": [],
    }
    tracked_ciks = repository.tracked_ciks()
    if not tracked_ciks:
        raise RuntimeError("gating universe is empty; check universe.tracked and CIK values")

    display_tickers = repository.tickers_by_cik()
    last_by_cik = repository.last_filed_map()
    processed_by_cik = repository.processed_filing_accessions()
    updates: list[tuple[int, list, list]] = []
    index_end = datetime.now(ZoneInfo("America/New_York")).date()

    requested_tickers = {str(ticker) for ticker in (target_tickers or set()) if ticker}
    if requested_tickers:
        candidate_ciks = {int(cik) for cik in repository.ciks_for_tickers(requested_tickers)}
        index_files = 0
        log.info(
            "scheduled report path: tickers=%d candidate_ciks=%d",
            len(requested_tickers), len(candidate_ciks),
        )
    elif watchlist_only:
        watchlist = repository.watchlist_tickers()
        ticker_to_cik = {
            str(row["ticker"]): str(row["cik"]).zfill(10)
            for row in repository.gating_universe()
            if row.get("ticker") and row.get("cik")
        }
        candidate_ciks = {
            int(ticker_to_cik[ticker])
            for ticker in watchlist
            if ticker in ticker_to_cik
        }
        index_files = 0
        log.info(
            "watchlist fast path: tickers=%d candidate_ciks=%d",
            len(watchlist),
            len(candidate_ciks),
        )
    else:
        candidate_ciks, index_files = source.recent_financial_ciks(
            tracked_ciks={int(cik) for cik in tracked_ciks},
            end=index_end,
            lookback_days=lookback_days,
        )
    metrics["index_files"] = index_files
    metrics["ciks_indexed"] = len(candidate_ciks)

    for cik in sorted(candidate_ciks):
        cik_key = f"{cik:010d}"
        tickers = display_tickers.get(cik_key, [])
        metrics["ciks_scanned"] += 1
        if earnings_event_detector is not None:
            for ticker in tickers:
                try:
                    event_result = earnings_event_detector(
                        ticker,
                        f"{cik:010d}",
                    )
                    metrics["earnings_events"] += event_result["rows"]
                except Exception as exc:  # noqa: BLE001 - 재무 공시 적재는 계속한다
                    log.warning("8-K earnings event failed for %s: %r", ticker, exc)
                    metrics["failures"].append({
                        "ticker": ticker,
                        "stage": "earnings_event",
                        "error": repr(exc),
                    })

        try:
            filings = source.financial_filings(source.submissions(cik))
            pending = source.pending_filings(
                filings,
                last_by_cik.get(cik_key),
                processed_by_cik.get(cik_key, set()),
            )
            if pending:
                updates.append((cik, filings, pending))
        except Exception as exc:  # noqa: BLE001 - 다른 회사는 계속한다
            message = f"submission discovery failed for CIK {cik:010d}: {exc!r}"
            metrics["failures"].append({
                "cik": cik,
                "stage": "discovery",
                "error": repr(exc),
            })
            log.error(message)

    log.info(
        "SEC discovery complete: index_files=%d indexed_ciks=%d "
        "submissions_scanned=%d changed_ciks=%d",
        metrics["index_files"],
        metrics["ciks_indexed"],
        metrics["ciks_scanned"],
        len(updates),
    )

    for cik, filings, pending in updates:
        try:
            cik_key = f"{cik:010d}"
            facts = source.companyfacts_to_facts(
                source.companyfacts(cik),
                filings=filings,
                target_accessions={filing.accession_no for filing in pending},
                floor=resolve_backfill_window(
                    None,
                    default_years=_COMPANY_BACKFILL_YEARS,
                ).start,
                allowed_keys=COMPANYFACT_COLUMNS,
                allow_filing_fallback=True,
            )
            if not facts:
                repository.mark_empty_filing_targets(
                    [(filing, cik_key) for filing in pending],
                    source="daily_companyfacts",
                )
                metrics["ciks"] += 1
                log.info(
                    "CIK %010d has %d filing(s) with no selected facts; marked empty",
                    cik,
                    len(pending),
                )
                continue

            loaded = process_company_facts(
                facts, filings=filings, repository=repository
            )
            rows_by_accession = loaded["rows_by_accession"]
            loaded_accessions = set(rows_by_accession)
            completed_filings = [
                filing
                for filing in pending
                if filing.accession_no in loaded_accessions
            ]
            missing_filings = [
                filing
                for filing in pending
                if filing.accession_no not in loaded_accessions
            ]
            if missing_filings:
                repository.mark_empty_filing_targets(
                    [(filing, cik_key) for filing in missing_filings],
                    source="daily_companyfacts",
                )
                log.info(
                    "CIK %010d has no selected facts for %d accession_no(s); marked empty",
                    cik,
                    len(missing_filings),
                )
            fact_counts: dict[str, int] = {}
            for fact in facts:
                accession_no = str(fact.get("accession_no") or "")
                if accession_no:
                    fact_counts[accession_no] = fact_counts.get(accession_no, 0) + 1
            repository.mark_processed_filing_targets(
                [
                    (
                        filing,
                        cik_key,
                        fact_counts[filing.accession_no],
                        rows_by_accession[filing.accession_no],
                    )
                    for filing in completed_filings
                ],
                source="daily_companyfacts",
            )
            for key in ("rows", "core_rows", "quarantined"):
                metrics[key] += loaded[key]
            metrics["ciks"] += 1
            metrics["filings"] += len(completed_filings)
        except Exception as exc:  # noqa: BLE001 - 부분 성공은 보존한다
            message = f"companyfacts load failed for CIK {cik:010d}: {exc!r}"
            metrics["failures"].append({
                "cik": cik,
                "stage": "load",
                "error": repr(exc),
            })
            log.error("%s\n%s", message, traceback.format_exc())
    log.info("recent company filings sync complete: %s", metrics)
    return metrics


def sync_segment_filings(
    period_kind: str,
    *,
    source: SegmentFilingSource,
    repository: SegmentMetricRepository,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    reprocess: bool = False,
    watchlist_only: bool = False,
    target_tickers: set[str] | None = None,
) -> dict:
    """최근 XBRL 공시의 사업·지역·제품 세그먼트를 증분 동기화한다."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")

    tracked_ciks = repository.tracked_ciks()
    forms = segment_forms(period_kind)
    end = datetime.now(ZoneInfo("America/New_York")).date()
    filed_cutoff = end - timedelta(days=lookback_days - 1)
    requested_tickers = {
        str(ticker).strip().upper()
        for ticker in (target_tickers or set())
        if str(ticker).strip()
    }
    if requested_tickers:
        selected_ciks = repository.ciks_for_tickers(requested_tickers)
        index_files = 0
    elif watchlist_only:
        watchlist = {
            str(ticker).strip().upper()
            for ticker in repository.watchlist_tickers()
            if str(ticker).strip()
        }
        selected_ciks = repository.ciks_for_tickers(watchlist) if watchlist else set()
        index_files = 0
    else:
        selected_ciks = set(tracked_ciks)
    if requested_tickers or watchlist_only:
        candidate_ciks = {int(cik) for cik in selected_ciks}
        path = "scheduled" if requested_tickers else "watchlist"
        log.info(
            "segments %s path: tickers=%d candidate_ciks=%d",
            path,
            len(selected_ciks),
            len(candidate_ciks),
        )
    else:
        candidate_ciks, index_files = source.recent_filing_ciks(
            tracked_ciks={int(cik) for cik in selected_ciks},
            forms=forms,
            end=end,
            lookback_days=lookback_days,
        )

    existing = repository.existing_accessions(forms)
    reprocess_targets: dict[str, set[str]] = {}
    if reprocess:
        reprocess_targets = repository.accessions_by_source(
            _REPROCESS_SOURCES,
            forms,
        )
        for cik, accessions in reprocess_targets.items():
            existing.get(cik, set()).difference_update(accessions)
        log.info(
            "segments reprocess: source=%s targets=%d companies/%d filings",
            ",".join(_REPROCESS_SOURCES),
            len(reprocess_targets),
            sum(len(values) for values in reprocess_targets.values()),
        )
    metrics = {
        "wide_rows": 0,
        "derived_q4_rows": 0,
        "filings": 0,
        "companies": len(tracked_ciks),
        "companies_processed": len(candidate_ciks),
        "candidate_ciks": len(candidate_ciks),
        "index_files": index_files,
        "filings_discovered": 0,
        "skipped_existing": 0,
        "missing_documents": [],
        "failures": [],
        "unmapped_concepts": set(),
    }
    log.info(
        "segments sync period=%s universe=%d candidate_ciks=%d index_files=%d",
        period_kind,
        len(tracked_ciks),
        len(candidate_ciks),
        index_files,
    )
    if not candidate_ciks:
        return metrics

    worker_count = min(
        int(os.environ.get("FUNDAMENTALS_SEGMENT_WORKERS", str(_MAX_SEGMENT_WORKERS))),
        len(candidate_ciks),
    )
    with ThreadPoolExecutor(max_workers=max(worker_count, 1)) as executor:
        futures = {
            executor.submit(
                process_segment_cik,
                cik=cik,
                forms=forms,
                filed_cutoff=filed_cutoff,
                existing=existing,
                period_kind=period_kind,
                source=source,
            ): cik
            for cik in sorted(candidate_ciks)
        }
        for future in as_completed(futures):
            cik = futures[future]
            try:
                result = future.result()
                persisted = persist_segment_filings(
                    result["filing_rows"],
                    result["wide_rows"],
                    result.get("ytd_rows"),
                    replace={
                        (str(row["cik"]), str(row["accession_no"]))
                        for row in result["filing_rows"]
                        if str(row["accession_no"])
                        in reprocess_targets.get(str(row["cik"]), ())
                    },
                    repository=repository,
                )
                for key in ("filings", "wide_rows", "derived_q4_rows"):
                    metrics[key] += persisted[key]
                metrics["filings_discovered"] += result["filings_discovered"]
                metrics["skipped_existing"] += result["skipped_existing"]
                metrics["missing_documents"].extend(result["missing_documents"])
                metrics["failures"].extend(result.get("failures", []))
                metrics["unmapped_concepts"].update(
                    result.get("unmapped_concepts", [])
                )
                for row in result["filing_rows"]:
                    if row["status"] in {"parsed", "empty", "unsupported"}:
                        existing.setdefault(row["cik"], set()).add(row["accession_no"])
            except Exception as exc:  # noqa: BLE001 - 다른 CIK 진행은 보존한다
                log.error("segments sync CIK=%s failed: %s", cik, exc)
                metrics["failures"].append({"cik": cik, "error": repr(exc)})
    return metrics
