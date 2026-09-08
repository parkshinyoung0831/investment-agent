"""기업 전체 또는 세그먼트 재무 이력을 백필하는 canonical 잡."""
from __future__ import annotations

import argparse
import traceback

from investment_agent.operations.backfill import add_backfill_from_arg, add_backfill_scope_arg
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.data.fundamentals.commands.backfill_history")
    parser.add_argument(
        "--content",
        choices=("company", "segments"),
        default="company",
    )
    parser.add_argument("--period", choices=("quarter", "annual"))
    parser.add_argument(
        "--tickers",
        help="백필 대상을 쉼표로 제한한다. 미추적 ticker는 실패한다.",
    )
    add_backfill_from_arg(parser)
    add_backfill_scope_arg(parser, default="gaps")
    args = parser.parse_args(argv)
    if args.content == "segments" and args.period is None:
        parser.error("--content segments에는 --period가 필요하다")
    return args


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    try:
        from investment_agent.data.fundamentals.application.backfill_history import (
            backfill_company_history,
            backfill_segment_history,
            prune_segment_history,
        )
        from investment_agent.data.fundamentals.infrastructure.sec import companyfacts
        from investment_agent.data.fundamentals.infrastructure.sec import fsds
        from investment_agent.data.fundamentals.infrastructure.supabase import (
            company_financials,
            segment_metrics,
        )

        target_tickers = {
            ticker.strip().upper()
            for ticker in (args.tickers or "").split(",")
            if ticker.strip()
        }
        if args.content == "company":
            metrics = backfill_company_history(
                source=companyfacts,
                repository=company_financials,
                backfill_from=args.backfill_from,
                scope=args.scope,
                target_tickers=target_tickers or None,
            )
        else:
            metrics = backfill_segment_history(
                args.period,
                source=fsds,
                repository=segment_metrics,
                backfill_from=args.backfill_from,
                scope=args.scope,
                target_tickers=target_tickers or None,
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
        log.info(
            "history backfill complete content=%s scope=%s metrics=%s",
            args.content,
            args.scope,
            metrics,
        )
        return 1 if metrics.get("failures") else 0
    except Exception as exc:  # noqa: BLE001 - canonical CLI 경계
        log.error("history backfill failed: %s\n%s", exc, traceback.format_exc())
        return 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())

