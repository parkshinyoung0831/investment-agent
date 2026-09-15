"""System Portfolio를 평가하고 필요하면 목표비중을 다시 만든다. 실주문·실계좌·승인 원장에는 닿지 않는다.

    python -m investment_agent.operations.commands.system_portfolio            # 평가 → 목표 갱신
    python -m investment_agent.operations.commands.system_portfolio --summary  # 성과 요약
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json, parse_datetime

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.system_portfolio")
    parser.add_argument("--as-of", help="타임존을 포함한 ISO-8601 기준 시각. 기본은 현재 UTC")
    parser.add_argument("--summary", action="store_true", help="평가 없이 성과 요약만 출력")
    args = parser.parse_args(argv)
    from investment_agent.trading.system.accounting import performance_summary
    from investment_agent.trading.system.store import SystemPortfolioStore

    store = SystemPortfolioStore()
    if args.summary:
        log.info("system portfolio summary %s", canonical_json(performance_summary(store.history())))
        return 0
    from investment_agent.trading.supabase_repository import SupabaseRepository
    from investment_agent.trading.system.engine import run_system

    now = parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    result = run_system(store, SupabaseRepository(), now=now)
    log.info("system portfolio %s", canonical_json(result.to_dict()))
    return 0


__all__ = ["main"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
