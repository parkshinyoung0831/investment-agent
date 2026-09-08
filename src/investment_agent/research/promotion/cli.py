"""평가 원장을 재집계한 뒤 모델 수명주기를 수동으로 한 단계 승격한다."""
from __future__ import annotations

import argparse

from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.research.promotion.gate import ManualPromotionGate
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="investment_agent.research.promotion.cli",
        epilog=(
            "confirmation format: PROMOTE <artifact-id> "
            "<current-stage>-><target-stage>"
        ),
    )
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument(
        "--to-stage",
        choices=("backtest", "out_of_sample", "walk_forward", "paper", "live"),
        required=True,
    )
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--confirm", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    repository = SupabaseRepository()
    artifact = repository.model_artifact(args.artifact_id)
    if artifact is None:
        raise RuntimeError(f"model artifact not found: {args.artifact_id}")
    from_stage = repository.model_stage(args.artifact_id)
    if from_stage is None:
        raise RuntimeError(f"model stage not found: {args.artifact_id}")
    summary = repository.model_evaluation_summary(args.artifact_id)
    gate = ManualPromotionGate()
    decision = gate.propose(
        args.artifact_id,
        from_stage=from_stage,
        to_stage=args.to_stage,
        summary=summary,
    )
    if decision.status == "rejected":
        repository.save_promotion(decision.to_record())
        raise RuntimeError("model promotion rejected: " + "; ".join(decision.violations))
    approved = gate.approve(
        decision,
        approved_by=args.approved_by,
        confirmation=args.confirm,
    )
    audit = repository.approve_model_promotion(
        approved,
        confirmation=args.confirm,
    )
    log.info(
        "model promotion approved artifact_id=%s transition=%s->%s promotion_id=%s",
        args.artifact_id,
        from_stage,
        args.to_stage,
        audit.get("promotion_id"),
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
