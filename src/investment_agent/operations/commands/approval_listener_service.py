"""Discord 승인 Gateway listener를 별도 lock으로 감싸는 로컬 서비스 entry."""
from __future__ import annotations

import argparse
from importlib import import_module
from pathlib import Path
from typing import Callable

from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.operations.harness.lock import DuplicateProcessError, ProcessFileLock
from investment_agent.operations.harness.reporting import DiscordOpsAlert, HarnessReporter

log = get_logger(__name__)
from investment_agent.operations.paths import HARNESS_STATE_DIR as _DEFAULT_STATE_DIR


def _listener_main() -> int:
    module = import_module("investment_agent.operations.commands.approval_listener")
    return int(module.main())


def main(
    argv: list[str] | None = None,
    *,
    listener: Callable[[], int] = _listener_main,
) -> int:
    parser = argparse.ArgumentParser(description="Discord 투자 승인 Gateway 서비스")
    parser.add_argument("--state-dir", default=str(_DEFAULT_STATE_DIR))
    args = parser.parse_args(argv)
    configure_logging()
    reporter = HarnessReporter(logger=log, alerts=DiscordOpsAlert(log))
    lock = ProcessFileLock(
        Path(args.state_dir).expanduser().resolve() / "approval_listener.lock"
    )
    try:
        lock.acquire()
    except DuplicateProcessError:
        reporter.error("approval_listener_duplicate_process")
        return 2
    try:
        reporter.event("approval_listener_started")
        return listener()
    except Exception as exc:  # Gateway 오류 문구에는 token이 있을 수 있어 타입만 기록한다.
        reporter.error(
            "approval_listener_failed",
            error_type=type(exc).__name__,
        )
        return 1
    finally:
        lock.release()
        reporter.event("approval_listener_stopped")


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
