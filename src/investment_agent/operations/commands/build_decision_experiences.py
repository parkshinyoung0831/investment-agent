"""원본 판단과 사후 가격을 이어 판단 경험(decision experience)을 만든다.

Trading 판단 원장(`SupabaseRepository`)을 조립하는 운영 진입점이다. 경험 계산은 Research가 소유한다.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import parse_datetime
from investment_agent.research.commands.build_decision_experiences import run
from investment_agent.trading.supabase_repository import SupabaseRepository

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--as-of", help="타임존을 포함한 평가 기준 시각")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")
    count = run(SupabaseRepository(), as_of_at=parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc), limit=args.limit, dry_run=args.dry_run)
    log.info("decision experiences saved=%d dry_run=%s", count, args.dry_run)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
