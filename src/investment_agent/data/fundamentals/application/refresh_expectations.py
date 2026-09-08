"""시장 컨센서스·발표 예정일·애널리스트 커버리지를 갱신한다."""
from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import date

from investment_agent.platform.clock import us_market_today
from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.application.analyst_coverage import (
    changed_analyst_snapshots,
)
from investment_agent.data.fundamentals.application.earnings_estimates import (
    build_earnings_estimates,
)
from investment_agent.data.fundamentals.application import ConsensusSource, ExpectationsRepository

log = get_logger(__name__)

_DEFAULT_REQUEST_GAP_SEC = 0.3
_DEFAULT_MAX_WORKERS = 4


class CollectionBudgetExceeded(RuntimeError):
    """수집 예산을 넘겨 이번 관측 묶음을 저장하지 않을 때 사용한다."""

    def __init__(self, *, budget_sec: float, elapsed_sec: float, processed: int, total: int):
        self.budget_sec = budget_sec
        self.elapsed_sec = elapsed_sec
        self.processed = processed
        self.total = total
        super().__init__(
            f"수집 예산 초과: {elapsed_sec:.1f}초 >= {budget_sec:.1f}초 "
            f"({processed}/{total} 종목 처리 뒤)"
        )


def collect_expectations(
    tickers: list[str],
    *,
    source: ConsensusSource,
    repository: ExpectationsRepository,
    today: date | None = None,
    request_gap_sec: float = _DEFAULT_REQUEST_GAP_SEC,
    collection_budget_sec: float | None = None,
    max_workers: int = _DEFAULT_MAX_WORKERS,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """종목별 시장 예상치를 모아 결과 종류별 bucket으로 반환한다."""
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")
    tickers = list(dict.fromkeys(tickers))
    today = today or us_market_today()
    buckets: dict[str, list[dict]] = {
        "snapshots": [],
        "trend_seed": [],
        "analyst_snapshots": [],
    }
    if not tickers:
        return buckets, []

    seed_targets = repository.tickers_missing_consensus(tickers)
    if seed_targets:
        log.info("eps_trend 90일 소급 대상: %d 종목", len(seed_targets))

    failures: list[dict] = []
    started_at = monotonic()
    completed: dict[str, tuple[dict | None, Exception | None]] = {}
    futures = {}
    with ThreadPoolExecutor(
        max_workers=min(max_workers, len(tickers)),
        thread_name_prefix="expectations",
    ) as executor:
        for index, ticker in enumerate(tickers):
            elapsed_sec = monotonic() - started_at
            if collection_budget_sec is not None and elapsed_sec >= collection_budget_sec:
                for future in futures:
                    future.cancel()
                raise CollectionBudgetExceeded(
                    budget_sec=collection_budget_sec,
                    elapsed_sec=elapsed_sec,
                    processed=len(completed),
                    total=len(tickers),
                )
            futures[executor.submit(source.fetch_consensus, ticker, today=today)] = ticker
            if index + 1 < len(tickers) and request_gap_sec > 0:
                time.sleep(request_gap_sec)

        elapsed_sec = monotonic() - started_at
        remaining_sec = (
            None
            if collection_budget_sec is None
            else max(collection_budget_sec - elapsed_sec, 0)
        )
        try:
            for future in as_completed(futures, timeout=remaining_sec):
                ticker = futures[future]
                try:
                    completed[ticker] = (future.result(), None)
                except Exception as exc:  # noqa: BLE001 - 다른 종목은 계속한다
                    completed[ticker] = (None, exc)
                elapsed_sec = monotonic() - started_at
                if (
                    collection_budget_sec is not None
                    and elapsed_sec >= collection_budget_sec
                ):
                    raise FuturesTimeoutError
        except FuturesTimeoutError as exc:
            for pending in futures:
                pending.cancel()
            elapsed_sec = max(monotonic() - started_at, collection_budget_sec or 0)
            raise CollectionBudgetExceeded(
                budget_sec=collection_budget_sec or 0,
                elapsed_sec=elapsed_sec,
                processed=len(completed),
                total=len(tickers),
            ) from exc

    for ticker in tickers:
        result, error = completed[ticker]
        if error is not None:
            log.warning("expectations failed ticker=%s error=%s", ticker, error)
            failures.append({"ticker": ticker, "error": repr(error)})
            continue
        if result is None:
            continue
        failures.extend({"ticker": ticker, **failure} for failure in (
            result.get("source_failures") or []
        ))
        buckets["snapshots"].extend(result.get("snapshots", []))
        analyst_snapshot = result.get("analyst_snapshot")
        if analyst_snapshot:
            buckets["analyst_snapshots"].append(analyst_snapshot)
        if ticker in seed_targets:
            buckets["trend_seed"].extend(result.get("trend_seed", []))
    return buckets, failures


def persist_expectations(
    buckets: dict[str, list[dict]],
    fiscal_calendar_rows: list[dict],
    *,
    expectations_repository: ExpectationsRepository,
    today: date,
) -> tuple[dict[str, int], list[dict]]:
    """상대 기간을 표준 회계기간에 맞춘 뒤 각 저장소에 적재한다."""
    batch = build_earnings_estimates(buckets, fiscal_calendar_rows, collected_on=today)
    analyst_snapshots = buckets.get("analyst_snapshots", [])
    changed_analyst = changed_analyst_snapshots(
        analyst_snapshots,
        expectations_repository.latest_analyst_snapshots(
            [str(snapshot["ticker"]) for snapshot in analyst_snapshots]
        ) if analyst_snapshots else [],
    )
    counts = {
        "consensus": expectations_repository.upsert_consensus(batch.snapshots),
        "schedules": expectations_repository.upsert_schedules(batch.schedules),
        "analyst_coverage": expectations_repository.upsert_analyst_snapshots(changed_analyst),
    }
    return counts, list(batch.unmapped_rows)


def refresh_expectations(
    tickers: list[str],
    *,
    source: ConsensusSource,
    expectations_repository: ExpectationsRepository,
    today: date | None = None,
    request_gap_sec: float = _DEFAULT_REQUEST_GAP_SEC,
    collection_budget_sec: float | None = None,
    max_workers: int = _DEFAULT_MAX_WORKERS,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict:
    """지정 종목의 예상치를 수집·정규화·저장한다."""
    today = today or us_market_today()
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        log.info("expectations target count is 0; skipping")
        return {"tickers": 0, "rows": 0, "failures": [], "counts": {}}

    fiscal_calendar_rows = expectations_repository.fiscal_periods(tickers)
    try:
        buckets, failures = collect_expectations(
            tickers,
            source=source,
            repository=expectations_repository,
            today=today,
            request_gap_sec=request_gap_sec,
            collection_budget_sec=collection_budget_sec,
            max_workers=max_workers,
            monotonic=monotonic,
        )
    except CollectionBudgetExceeded as exc:
        failure = {
            "type": "collection_budget_exceeded",
            "budget_sec": exc.budget_sec,
            "elapsed_sec": round(exc.elapsed_sec, 3),
            "processed": exc.processed,
            "total": exc.total,
        }
        log.warning("expectations collection discarded: %s", failure)
        return {
            "tickers": exc.processed,
            "rows": 0,
            "failures": [failure],
            "counts": {},
            "discarded": True,
        }
    counts, unmapped = persist_expectations(
        buckets,
        fiscal_calendar_rows,
        expectations_repository=expectations_repository,
        today=today,
    )
    failures.extend(unmapped)
    total = sum(counts.values())
    retention = {}
    if not failures:
        try:
            retention = expectations_repository.prune_earnings_estimates()
            # 나이 기준 정리 뒤에, 발표가 끝난 기간을 계약이 읽는 한 건씩만 남긴다.
            retention = {**retention, **expectations_repository.prune_expectation_snapshots()}
        except Exception as exc:  # noqa: BLE001 - 적재 건수와 실패를 함께 기록한다
            failures.append({
                "stage": "consensus_retention",
                "error": repr(exc),
            })
    log.info(
        "expectations refreshed tickers=%d rows=%d failures=%d counts=%s",
        len(tickers), total, len(failures), counts,
    )
    return {
        "tickers": len(tickers),
        "rows": total,
        "failures": failures,
        "counts": counts,
        "retention": retention,
    }
