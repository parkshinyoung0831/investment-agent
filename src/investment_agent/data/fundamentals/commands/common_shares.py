"""SEC 보통주 발행주식수 수집 및 백필 엔트리포인트."""
from __future__ import annotations

import argparse
import time
from datetime import date, timedelta

from investment_agent.operations.backfill import add_backfill_from_arg, resolve_backfill_window
from investment_agent.operations.runtime import EXIT_FAILED, EXIT_OK, EXIT_PARTIAL, elapsed_sec, notify_ops
from investment_agent.platform.logging import get_logger
from investment_agent.operations.monitoring.incidents import (
    build_incident_embed,
    build_runtime_incident,
    current_github_run_url,
)
from investment_agent.data.fundamentals.infrastructure.sec.common_shares import fetch_cik_common_shares
from investment_agent.data.fundamentals.infrastructure.supabase.share_class_snapshots import (
    load_shares_outstanding_by_cik,
    replace_shares_outstanding,
)
from investment_agent.data.fundamentals.domain.services.parse_shares import validate_shares_outstanding
from investment_agent.data.universe import persistence as universe_db

log = get_logger(__name__)

_DEFAULT_LOOKBACK_YEARS = 10
_INCREMENTAL_OVERLAP_DAYS = 120


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.data.fundamentals.commands.common_shares")
    add_backfill_from_arg(parser)
    parser.add_argument(
        "--scope",
        choices=("all", "missing", "gaps"),
        default="gaps",
        help="all fetches all tracked CIKs; missing only CIKs with no rows; gaps checks recent filings.",
    )
    parser.add_argument(
        "--target-ciks",
        nargs="*",
        default=None,
        help="Optional specific CIKs to collect.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    t0 = time.monotonic()
    args = _parse_args(argv)
    window = resolve_backfill_window(args.backfill_from, default_years=_DEFAULT_LOOKBACK_YEARS)

    # 1. Tracked CIKs and their securities
    tracked_ciks = universe_db.select_tracked_ciks()
    if args.target_ciks:
        wanted_ciks = {str(c).strip().zfill(10) for c in args.target_ciks}
        tracked_ciks = [c for c in tracked_ciks if c in wanted_ciks]

    # Map CIK to active tickers
    tickers_by_cik = universe_db.select_common_stock_tickers_by_cik()

    log.info(
        "Common shares collection start: ciks=%d scope=%s cutoff=%s",
        len(tracked_ciks),
        args.scope,
        window.start.isoformat(),
    )

    total_rows = 0
    ciks_processed = 0
    failures: list[str] = []

    for cik in tracked_ciks:
        existing = load_shares_outstanding_by_cik(cik)
        if args.scope == "missing" and existing:
            continue
        collection_cutoff = window.start
        if args.scope == "gaps" and existing:
            latest_filed = max(date.fromisoformat(str(row["filed_at"])) for row in existing)
            collection_cutoff = max(
                window.start, latest_filed - timedelta(days=_INCREMENTAL_OVERLAP_DAYS)
            )

        tickers = tickers_by_cik.get(cik, [])
        try:
            shares_rows = fetch_cik_common_shares(
                cik,
                cutoff=collection_cutoff,
                active_tickers=tickers,
            )
            retained = [
                row
                for row in existing
                if date.fromisoformat(str(row["filed_at"])) < collection_cutoff
            ]
            validate_shares_outstanding([*retained, *shares_rows])
            counts = replace_shares_outstanding(
                cik,
                filed_from=collection_cutoff.isoformat(),
                rows=shares_rows,
            )
            total_rows += counts["upserted"]
            ciks_processed += 1
        except Exception as exc:
            log.error("CIK %s common shares collection failed: %s", cik, exc)
            failures.append(f"{cik}: {type(exc).__name__}: {exc}")

    log.info(
        "Common shares collection complete: ciks=%d rows_written=%d duration_sec=%.1f",
        ciks_processed,
        total_rows,
        elapsed_sec(t0),
    )
    if failures:
        log.error(
            "Common shares collection incomplete: failed_ciks=%d failures=%s",
            len(failures),
            failures[:20],
        )
        # 전부 실패면 수집 자체가 깨진 것이고, 일부면 그 CIK만 원천이 이상한 것이다.
        conclusion = "failure" if ciks_processed == 0 else "partial"
        incident = build_runtime_incident(
            workflow="fundamentals_common_shares",
            step="SEC 보통주 발행주식수 수집",
            summary=f"CIK {len(failures)}개 실패 · " + " | ".join(failures[:5]),
            conclusion=conclusion,
            impact="실패한 CIK의 발행주식수 최신값이 갱신되지 않았어요.",
            action="GitHub Actions 원문 로그에서 실패 CIK와 SEC 응답을 확인한 뒤 다시 실행해 주세요.",
            url=current_github_run_url(),
        )
        notify_ops("", logger=log, embeds=[build_incident_embed(incident)])
        return EXIT_FAILED if conclusion == "failure" else EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
