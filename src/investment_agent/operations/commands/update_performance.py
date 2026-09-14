"""실행·판단 원천에서 성과 보고서를 생산한다. 발송은 notify가 담당한다."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from investment_agent.execution.db import ExecutionRepository
from investment_agent.platform.logging import get_logger
from investment_agent.trading.performance.service import update_performance
from investment_agent.platform.serialization import parse_datetime

log = get_logger(__name__)


def main(argv=None):
    from investment_agent.trading.supabase_repository import SupabaseRepository

    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of")
    args = parser.parse_args(argv)
    as_of = parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    source = ExecutionRepository()
    research = SupabaseRepository()
    rows = research.decision_experience_rows(as_of_at=as_of)
    result = update_performance(source=source, recommendation_rows=rows, as_of_at=as_of)
    log.info("performance reports updated: %s", result)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
