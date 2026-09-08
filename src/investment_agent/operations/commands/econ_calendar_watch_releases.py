"""Release-time ECON watcher. GitHub Actions와 local harness가 같은 entrypoint를 호출한다."""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.data.macro.application import release_calendar as etl

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.econ_calendar_watch_releases")
    parser.add_argument("--poll-attempts", type=int, default=4)
    parser.add_argument("--poll-interval-seconds", type=int, default=20)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.poll_attempts <= 6:
        parser.error("--poll-attempts must be between 1 and 6")
    if not 1 <= args.poll_interval_seconds <= 60:
        parser.error("--poll-interval-seconds must be between 1 and 60")

    from investment_agent.config import load_config
    from investment_agent.data.macro.releases import db
    from investment_agent.platform.db.postgres import Database
    db.configure(Database.from_config(load_config()))
    db.seed_catalog()

    confirmed: set[str] = set()
    failures: list[dict] = []
    last: dict = {}
    for attempt in range(args.poll_attempts):
        last = etl.watch_once(now=datetime.now(timezone.utc), limit=args.limit)
        confirmed.update(last.get("first_actual_event_keys", []))
        failures.extend(last.get("failures", []))
        if last.get("due", 0) == 0 or last.get("first_actuals", 0) > 0:
            break
        if attempt + 1 < args.poll_attempts:
            time.sleep(args.poll_interval_seconds)

    notified = 0
    notification_failed = False
    # 이미 actual이 들어와 due가 없어도 이전 발송 실패를 다시 시도한다.
    if args.notify:
        try:
            from investment_agent.notifications.econ_calendar.run import run

            notified = run()
        except Exception as exc:
            log.exception("ECON watcher notification failed: %s", type(exc).__name__)
            notification_failed = True

    log.info(
        "econ release watch done: due=%d first_actuals=%d notified=%d not_available=%d failures=%d",
        last.get("due", 0), len(confirmed), notified, last.get("not_available", 0), len(failures),
    )
    # 중간 polling 실패가 후속 시도에서 복구되면 성공으로 본다. 마지막 시도에도
    # provider 오류가 남거나 알림 전송이 실패한 경우에만 재실행 가능한 실패로 종료한다.
    unresolved_failures = last.get("failures", [])
    return 1 if unresolved_failures or notification_failed else 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
