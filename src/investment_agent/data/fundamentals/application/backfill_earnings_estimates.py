"""과거 8-K 실적 속보에 EPS 예상치 재구성값을 채운다."""
from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.application.historical_earnings_estimates import (
    build_historical_eps_estimates,
)
from investment_agent.data.fundamentals.application import (
    EarningsEventRepository,
    ExpectationsRepository,
    ReportedEarningsSource,
)

log = get_logger(__name__)
_DEFAULT_REQUEST_GAP_SEC = 0.3


def backfill_historical_eps_estimates(
    *,
    tickers: list[str] | None,
    flash_repository: EarningsEventRepository,
    expectations_repository: ExpectationsRepository,
    source: ReportedEarningsSource,
    request_gap_sec: float = _DEFAULT_REQUEST_GAP_SEC,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """기존 실적 속보에만 Yahoo의 과거 EPS 예상치를 재구성해 저장한다."""
    flash_rows = flash_repository.load_earnings_results(tickers)
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in flash_rows:
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            by_ticker[ticker].append(row)

    snapshots: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    skipped: list[dict[str, str | None]] = []
    for index, ticker in enumerate(sorted(by_ticker)):
        if index and request_gap_sec > 0:
            sleep(request_gap_sec)
        try:
            reported = source.fetch_reported_earnings(ticker)
        except Exception as exc:  # noqa: BLE001 - 다른 종목의 재구성은 계속한다
            log.warning("historical EPS backfill failed ticker=%s error=%s", ticker, exc)
            failures.append({"ticker": ticker, "error": repr(exc)})
            continue
        batch = build_historical_eps_estimates(by_ticker[ticker], reported)
        snapshots.extend(batch.snapshots)
        skipped.extend(batch.skipped)

    written = expectations_repository.upsert_consensus(snapshots)
    metrics = {
        "tickers": len(by_ticker),
        "flash_rows": len(flash_rows),
        "reconstructed_rows": written,
        "skipped": skipped,
        "failures": failures,
    }
    log.info("historical EPS backfill complete metrics=%s", metrics)
    return metrics


__all__ = ["backfill_historical_eps_estimates"]
