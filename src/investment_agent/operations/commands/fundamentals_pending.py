"""미발송 펀더멘탈 알림 상태를 GitHub Actions 출력으로 기록한다.

속보(8-K embed)와 정밀 카드(10-Q PNG)는 필요한 의존성이 다르다. 속보는 requests만
있으면 되고 카드는 Playwright·CJK 폰트까지 필요하다. 두 상태를 따로 내보내야
워크플로가 "이번엔 무엇을 설치할지"를 정확히 고를 수 있다.

두 패키지를 모두 읽으므로 어느 한쪽 안에 둘 수 없다. `earnings_report` 안에 있으면
그 패키지가 `earnings_flash`를 import하게 되고, 그건 알림 패키지끼리 서로를 부르지
않는다는 경계를 깬다.
"""
from __future__ import annotations

import argparse
import pathlib

from investment_agent.notifications.earnings_report import candidates
from investment_agent.config import load_config
from investment_agent.notifications.earnings_flash.candidates import pending_count
from investment_agent.reporting.notifications.earnings_flash import EarningsFlashStore
from investment_agent.platform.db.postgres import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.fundamentals_pending")
    parser.add_argument("--github-output", required=True)
    args = parser.parse_args(argv)

    state = candidates.pending_state()
    pending_flash = pending_count(EarningsFlashStore(Database.from_config(load_config())))
    output = pathlib.Path(args.github_output)
    with output.open("a", encoding="utf-8") as stream:
        stream.write(
            f"should_notify={'true' if state['should_notify'] else 'false'}\n"
            f"should_flash={'true' if pending_flash else 'false'}\n"
            f"watchlist_count={state['watchlist_count']}\n"
            f"pending_filings={state['pending_filings']}\n"
            f"pending_flash={pending_flash}\n"
        )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
