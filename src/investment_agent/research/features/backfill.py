"""Technical indicators backfill entrypoint."""
from __future__ import annotations

import argparse
from datetime import timedelta

from investment_agent.operations.backfill import (
    BackfillWindow,
    add_backfill_from_arg,
    resolve_backfill_window,
)
from investment_agent.research.features import BACKFILL_WARMUP_TRADING_DAYS, BACKFILL_YEARS


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.features.backfill")
    add_backfill_from_arg(parser)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    window = resolve_backfill_window(
        args.backfill_from,
        default_years=BACKFILL_YEARS,
    )
    from investment_agent.research.features.retention import RETENTION_DAYS, prune_history

    retention_start = window.end - timedelta(days=RETENTION_DAYS)
    save_from = max(window.start, retention_start)
    storage_window = BackfillWindow(start=save_from, end=window.end)
    rolling_days = storage_window.trading_days + BACKFILL_WARMUP_TRADING_DAYS

    from investment_agent.research.features.etl import run

    run(
        rolling_days=rolling_days,
        workflow="backfill",
        save_from=save_from,
    )
    prune_history(today=window.end)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
