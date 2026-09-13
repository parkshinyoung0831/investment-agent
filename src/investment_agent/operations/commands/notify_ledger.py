"""알림 원장 운영 명령 — topic 기준선을 세우고, 사람이 정한 알림을 다시 그리게 한다.

    # 원장을 처음 쓰기 시작할 때(또는 재구축 뒤) 모든 topic의 기준선을 지금으로 세운다.
    python -m investment_agent.operations.commands.notify_ledger baseline --all

    # 초기 구축 직후 최근 이틀치 사실은 보내고 싶을 때
    python -m investment_agent.operations.commands.notify_ledger baseline --all --hours-ago 48

    # 억제·포기·불명이었거나 이미 보낸 알림 하나를 다음 실행이 다시 그리게 한다.
    python -m investment_agent.operations.commands.notify_ledger replay earnings.report AVGO 0001730168-26-000099

기준선이 없는 topic은 원장이 발송을 거절한다(fail-closed). 기준선은 한 번 세우면 바꾸지
않는다 — 뒤로 옮기면 그 사이 사실이 한꺼번에 "새 소식"이 된다.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="python -m investment_agent.operations.commands.notify_ledger")
    commands = parser.add_subparsers(dest="command", required=True)
    baseline = commands.add_parser("baseline", help="topic 기준선을 세운다(이미 있으면 그대로 둔다)")
    group = baseline.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="카탈로그의 모든 topic")
    group.add_argument("--topic", action="append", default=[], help="특정 topic (반복 가능)")
    baseline.add_argument("--hours-ago", type=float, default=0.0,
                          help="기준선을 지금보다 이만큼 앞에 둔다(그 사이 사실은 보낸다)")
    replay = commands.add_parser("replay", help="알림 하나를 다음 실행이 다시 그리게 한다")
    replay.add_argument("topic")
    replay.add_argument("subject")
    replay.add_argument("occurrence")
    args = parser.parse_args(argv)

    from investment_agent.config import load_config
    from investment_agent.notifications.engine import default_context
    from investment_agent.notifications.topics import TOPICS, topic

    ledger = default_context(load_config()).ledger
    if args.command == "baseline":
        if not 0 <= args.hours_ago <= 24 * 30:
            parser.error("--hours-ago는 0~720이어야 합니다")
        names = sorted(TOPICS) if args.all else [topic(name).name for name in args.topic]
        at = datetime.now(timezone.utc) - timedelta(hours=args.hours_ago)
        for name in names:
            created = ledger.ensure_baseline(name, at)
            log.info("notification baseline topic=%s %s", name, "set" if created else "already set")
        return 0
    changed = ledger.replay(topic(args.topic).name, args.subject, args.occurrence)
    log.info("notification replay topic=%s subject=%s occurrence=%s changed=%d",
             args.topic, args.subject, args.occurrence, changed)
    return 0 if changed else 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    sys.exit(main())
