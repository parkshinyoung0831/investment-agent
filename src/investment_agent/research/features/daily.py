"""Daily technical indicators entrypoint."""
from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.research.features.daily")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute recent overlap even when max dates already match.",
    )
    args = parser.parse_args(argv)

    from investment_agent.research.features.etl import run
    from investment_agent.research.features.retention import prune_history

    run(workflow="daily", force=args.force)
    prune_history()
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
