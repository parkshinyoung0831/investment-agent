"""성숙한 Shadow 판단을 SPY 대비 5·20·60 거래일로 평가한다."""
from __future__ import annotations

import argparse

from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.research.evaluation.evaluator import evaluate_case
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.evaluate")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")

    repository = SupabaseRepository()
    saved = pending = 0
    for case in repository.cases_for_evaluation(args.limit):
        existing = repository.existing_evaluation_horizons(str(case["case_key"]))
        results = [row for row in evaluate_case(repository, case) if row.horizon_days not in existing]
        if not results:
            pending += 1
            continue
        if not args.dry_run:
            for result in results:
                repository.save_evaluation(result.to_dict())
        saved += len(results)
    log.info("shadow evaluation done new=%d pending_cases=%d dry_run=%s", saved, pending, args.dry_run)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())

