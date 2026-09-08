"""최신 세그먼트 XBRL 공시를 재처리하는 canonical 잡."""
from __future__ import annotations

import argparse
import os
import traceback

from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.data.fundamentals.commands.reprocess_filings")
    parser.add_argument("--period", choices=("quarter", "annual"), required=True)
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=int(os.environ.get("FUNDAMENTALS_SEGMENT_LOOKBACK_DAYS", "7")),
    )
    parser.add_argument("--watchlist-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    try:
        from investment_agent.data.fundamentals.application.backfill_history import (
            prune_segment_history,
        )
        from investment_agent.data.fundamentals.application.reprocess_filings import (
            reprocess_filings,
        )
        from investment_agent.data.fundamentals.infrastructure.sec import filing_documents
        from investment_agent.data.fundamentals.infrastructure.supabase import segment_metrics

        metrics = reprocess_filings(
            args.period,
            source=filing_documents,
            repository=segment_metrics,
            lookback_days=args.lookback_days,
            watchlist_only=args.watchlist_only,
        )
        if not metrics.get("failures"):
            metrics["retention"] = prune_segment_history(segment_metrics)
        unmapped = sorted(metrics.pop("unmapped_concepts", None) or [])
        if unmapped:
            log.warning(
                "segments unmapped concepts=%d top=%s",
                len(unmapped),
                ", ".join(unmapped[:15]),
            )
        log.info("filing reprocess complete period=%s metrics=%s", args.period, metrics)
        return 1 if metrics.get("failures") else 0
    except Exception as exc:  # noqa: BLE001 - canonical CLI 경계
        log.error("filing reprocess failed: %s\n%s", exc, traceback.format_exc())
        return 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
