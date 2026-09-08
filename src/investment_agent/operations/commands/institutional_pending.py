"""미발송 거장 알림 존재 여부를 GitHub Actions 출력으로 기록한다."""
from __future__ import annotations

import argparse
import pathlib

from investment_agent.notifications.institutional.state import pending_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.institutional_pending")
    parser.add_argument("--github-output", required=True)
    args = parser.parse_args(argv)

    state = pending_state()
    output = pathlib.Path(args.github_output)
    with output.open("a", encoding="utf-8") as stream:
        stream.write(
            f"should_notify={'true' if state['should_notify'] else 'false'}\n"
            f"pending_filings={state['pending_filings']}\n"
            f"summary_pending={'true' if state['summary_pending'] else 'false'}\n"
            f"period={state['period']}\n"
        )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
