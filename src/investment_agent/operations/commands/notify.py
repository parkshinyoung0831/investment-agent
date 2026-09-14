"""실행 진입점(entry point). --kind 값으로 보낼 알림을 골라 실행한다.
예) python -m investment_agent.operations.commands.notify --kind macro_core
각 알림은 run() 함수 하나만 노출하고, 이 파일이 그걸 대신 호출한다.

이미 보냈는지는 알림 원장이 판단하므로 몇 번을 불러도 사람에게는 한 번 닿는다.
`--force`는 원장을 무시하는 것이 아니라 같은 알림을 다시 그리게 한다 — 메시지가 있으면
그 메시지를 고치고, 없으면 새로 보낸다.
"""
from __future__ import annotations
import argparse
import asyncio
import importlib
import inspect
import os
import sys

from investment_agent.notifications.engine import REPLAY_ENV
from investment_agent.notifications.problems import report_problems, take_problems
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)

# 알림 종류 → 실행할 코드 위치("모듈경로:함수명") 매핑
KINDS: dict[str, str] = {
    "macro_core":    "investment_agent.notifications.macro.core:run",
    "macro_watch":   "investment_agent.notifications.macro.watch:run",
    "econ_calendar_release": "investment_agent.notifications.econ_calendar.run:run",
    "strategy":      "investment_agent.notifications.strategy.run:run",
    "fundamentals_earnings": "investment_agent.notifications.earnings_report.run:run",
    "fundamentals_flash": "investment_agent.notifications.earnings_flash.run:run",
    "fundamentals_calendar": "investment_agent.notifications.earnings_calendar.run:run",
    "gurus_13f": "investment_agent.notifications.institutional.run:run",
    # 자동매매 판단·체결. 파이프라인이 아니라 trading과 execution 원장이 원천이다.
    "investment_portfolio": "investment_agent.notifications.investment.run_portfolio:run",
    "investment_candidates": "investment_agent.notifications.investment.run_candidates:run",
    "investment_trades": "investment_agent.notifications.investment.run_trades:run",
    "investment_performance": "investment_agent.notifications.investment.run_performance:run",
}


def _dispatch(target: str) -> None:
    """위치 문자열("모듈경로:함수명")을 찾아 알림 함수를 실행한다."""
    mod_path, fn_name = target.split(":")
    fn = getattr(importlib.import_module(mod_path), fn_name)
    if inspect.iscoroutinefunction(fn):                      # async(기다림 필요) 함수면 asyncio로 실행
        asyncio.run(fn())
    else:
        fn()


def main() -> int:
    configure_logging()
    p = argparse.ArgumentParser(prog="python -m investment_agent.operations.commands.notify")
    p.add_argument("--kind", choices=list(KINDS), required=True)
    p.add_argument("--force", action="store_true", help="이미 보낸 알림도 다시 그린다(메시지가 있으면 수정)")
    args = p.parse_args()
    if args.force:
        os.environ[REPLAY_ENV] = "true"
    log.info("notify start kind=%s force=%s", args.kind, args.force)
    take_problems()                                          # 이 실행 전의 잔여를 섞지 않는다
    try:
        _dispatch(KINDS[args.kind])
    except Exception:
        log.exception("notify failed kind=%s", args.kind)
        return 1                                             # 1 = 실패 → 자동화가 실패로 감지
    # producer가 등록·전송 실패를 삼켜도 여기서 실패로 올린다. 초록색 잡이 곧 발송 완료다.
    if report_problems(f"notify:{args.kind}"):
        return 1
    log.info("notify done kind=%s", args.kind)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    sys.exit(main())
