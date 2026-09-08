"""Daily gurus 13F polling entrypoint."""
from __future__ import annotations

import argparse

from investment_agent.config import load_config
from investment_agent.data.institutional import POLL_WINDOW_DAYS
from investment_agent.data.institutional import persistence
from investment_agent.platform.db.postgres import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.data.institutional.commands.institutional_daily")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=POLL_WINDOW_DAYS,
        help="Overlapping SEC polling window; use backfill for long gaps.",
    )
    args = parser.parse_args(argv)
    if args.lookback_days < 1:
        parser.error("--lookback-days must be at least 1")

    persistence.configure(Database.from_config(load_config()))

    from investment_agent.data.institutional.application import etl
    from investment_agent.data.universe.infrastructure.sources import sec

    metrics = etl.run(lookback_days=args.lookback_days, sec_client=sec)
    return 1 if metrics["failures"] else 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
