"""Playwright 없이 실행하는 v1 실적 캘린더 Actions 사전 점검."""
from __future__ import annotations

import argparse
from pathlib import Path

from investment_agent.notifications.earnings_calendar.candidates import pending_state
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="investment_agent.notifications.earnings_calendar.pending")
    parser.add_argument("--github-output", required=True)
    args = parser.parse_args(argv)
    state = pending_state()
    log.info(
        "calendar preflight: week=%s upcoming=%s schedule_updates=%s should_notify=%s",
        state["iso_week"], state["upcoming_releases"], state["schedule_updates"],
        state["should_notify"],
    )
    with Path(args.github_output).open("a", encoding="utf-8") as stream:
        stream.write(f"should_notify={'true' if state['should_notify'] else 'false'}\n")
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
