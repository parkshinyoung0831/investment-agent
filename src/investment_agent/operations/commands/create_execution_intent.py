"""승격된 full portfolio RiskDecision을 paper/live intent로 발행한다."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from investment_agent.platform.serialization import parse_datetime
from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.operations.commands.approve_paper import validate_paper_scope
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.trading.portfolio.contracts import RiskDecision
from investment_agent.trading.risk.gate import DeterministicRiskGate
from investment_agent.platform.logging import get_logger
from investment_agent.execution.db import ExecutionRepository

log = get_logger(__name__)


def validate_promoted_execution_scope(
    proposal: dict,
    *,
    execution_mode: str,
    approved_weights: dict,
    current_tracked: set[str],
    now: datetime,
    max_snapshot_age_seconds: float = 300.0,
) -> str:
    validate_paper_scope(
        proposal,
        approved_weights=approved_weights,
        current_tracked=current_tracked,
    )
    if proposal.get("stage") != execution_mode:
        raise RuntimeError(f"{execution_mode} intent requires a fresh {execution_mode}-stage portfolio proposal")
    metadata = dict(proposal.get("metadata") or {})
    if metadata.get("execution_eligible") is not True:
        raise RuntimeError("portfolio proposal is not marked execution_eligible")
    captured_at = metadata.get("snapshot_captured_at")
    if not captured_at:
        raise RuntimeError("portfolio proposal has no snapshot_captured_at")
    age = (now - parse_datetime(str(captured_at))).total_seconds()
    if age < 0 or age > max_snapshot_age_seconds:
        raise RuntimeError("portfolio proposal account snapshot is stale")
    artifact_id = str(proposal.get("model_artifact_id") or "")
    if not artifact_id:
        raise RuntimeError("portfolio proposal has no model_artifact_id")
    signal_artifacts = metadata.get("signal_model_artifact_ids")
    if signal_artifacts is not None:
        if not isinstance(signal_artifacts, list) or not signal_artifacts:
            raise RuntimeError("portfolio proposal has empty or invalid signal_model_artifact_ids")
        if any(art != artifact_id for art in signal_artifacts):
            raise RuntimeError("portfolio proposal contains signals from mismatched model artifacts")
    return artifact_id


def create_execution_intent(
    *,
    risk_decision_id: str,
    execution_mode: str,
    confirmation: str,
    ttl_minutes: int = 15,
    now: str | datetime | None = None,
    repository: SupabaseRepository | None = None,
    execution_repository: ExecutionRepository | None = None,
) -> ExecutionIntent:
    """승격·snapshot을 재검증해 저장한 intent의 안정적 ID를 직접 반환한다."""
    if execution_mode not in {"paper", "live"}:
        raise ValueError("execution_mode must be paper or live")
    risk_decision_id = str(risk_decision_id).strip()
    if not risk_decision_id or confirmation != risk_decision_id:
        raise RuntimeError("confirmation must exactly match risk_decision_id")
    point = parse_datetime(now) if now is not None else datetime.now(timezone.utc)
    selected_repository = repository or SupabaseRepository()
    row = selected_repository.risk_decision(risk_decision_id)
    if row is None or not bool(row.get("is_approved")):
        raise RuntimeError("only an approved risk decision can create an execution intent")
    proposal = selected_repository.portfolio_proposal(str(row["proposal_id"]))
    if proposal is None:
        raise RuntimeError("portfolio proposal not found")
    approved_weights = dict(row.get("approved_weights") or {})
    artifact_id = validate_promoted_execution_scope(
        proposal,
        execution_mode=execution_mode,
        approved_weights=approved_weights,
        current_tracked=set(selected_repository.current_tracked_tickers()),
        now=point,
    )
    if not selected_repository.has_approved_promotion(artifact_id, execution_mode):
        raise RuntimeError(f"model artifact has not received manual promotion to {execution_mode}")
    signal_artifacts = dict(proposal.get("metadata") or {}).get("signal_model_artifact_ids") or [artifact_id]
    for art in signal_artifacts:
        if not selected_repository.has_approved_promotion(str(art), execution_mode):
            raise RuntimeError(f"signal model artifact {art} has not received manual promotion to {execution_mode}")
    decision = RiskDecision(
        risk_decision_id=str(row["risk_decision_id"]),
        proposal_id=str(row["proposal_id"]),
        policy_key=str(row["policy_key"]),
        policy_version=int(row["policy_version"]),
        policy_hash=str(row["policy_hash"]),
        input_hash=str(row["input_hash"]),
        is_approved=True,
        approved_weights=approved_weights,
        violations=tuple(row.get("violations") or ()),
        adjustments=tuple(row.get("adjustments") or ()),
        decided_at=str(row["decided_at"]),
    )
    intent = DeterministicRiskGate().create_execution_intent(
        decision,
        execution_mode=execution_mode,
        not_before=point,
        ttl_minutes=ttl_minutes,
    )
    (execution_repository or ExecutionRepository()).save_intent(intent.as_row())
    log.info(
        "%s execution intent created intent_id=%s artifact_id=%s expires_at=%s",
        execution_mode, intent.intent_id, artifact_id, intent.expires_at,
    )
    return intent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.create_execution_intent")
    parser.add_argument("--risk-decision-id", required=True)
    parser.add_argument("--execution-mode", choices=("paper", "live"), required=True)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--ttl-minutes", type=int, default=15)
    args = parser.parse_args(argv)
    create_execution_intent(
        risk_decision_id=args.risk_decision_id,
        execution_mode=args.execution_mode,
        confirmation=args.confirm,
        ttl_minutes=args.ttl_minutes,
    )
    return 0


__all__ = ["create_execution_intent", "main", "validate_promoted_execution_scope"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
