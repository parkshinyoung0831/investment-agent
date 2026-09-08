"""관심종목 fast path의 실적 시즌 게이트를 계산하는 canonical 잡."""
from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="investment_agent.data.fundamentals.commands.check_earnings_season"
    )
    parser.add_argument("--github-output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    try:
        from investment_agent.data.fundamentals.application.refresh_earnings_season import (
            github_output_lines,
            refresh_earnings_season,
        )
        from investment_agent.data.fundamentals.infrastructure.supabase import company_financials

        state = refresh_earnings_season(repository=company_financials)
        log.info(
            "earnings season checked in_season=%s reason=%s tickers=%s",
            state["in_season"],
            state["reason"],
            ",".join(state["tickers"]) or "-",
        )
        with Path(args.github_output).open("a", encoding="utf-8") as output:
            output.write(github_output_lines(state))
        return 0
    except Exception as exc:  # noqa: BLE001 - canonical CLI 경계
        log.error("earnings season check failed: %s\n%s", exc, traceback.format_exc())
        return 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())

