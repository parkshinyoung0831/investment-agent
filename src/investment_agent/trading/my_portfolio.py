"""My Portfolio: 실제 Toss 계좌가 현재 System 목표비중을 따라갈 주문 계획을 만든다.

실계좌는 판단의 입력이 아니다. 여기서 하는 일은 `System 목표비중 − 실제 계좌 비중`의 차이를 승인 가능한
기록으로 남기는 것뿐이고, System 목표·NAV는 이 모듈의 결과를 모른다.

- 따라가는 비중은 System이 승인한 목표 그대로다. 목표에 없는 보유(직접 산 종목 포함)는 0이다 — 전량 매도.
- 과거 거절·무응답을 복구하지 않는다. 오늘 따라가기로 하면 오늘의 목표와 오늘의 계좌 차이만 주문한다.
- 계좌가 이미 목표와 같으면(모든 차이가 최소 주문금액 미만) 승인을 묻지 않는다.
- 주문 금액은 계좌 전체(현금 + 보유 평가액) × 목표비중이다. 수량·소수점·매도 먼저·자금 부족 시 매도만은
  실행 계층(`execution.orders.planning`)이 같은 입력으로 다시 계산한다.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from investment_agent.execution.orders.planning import ExecutionLimits
from investment_agent.execution.orders.snapshots import AccountSnapshot
from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json, parse_datetime, stable_id
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL, PortfolioProposal, RiskDecision, validated_weights
from investment_agent.trading.risk.gate import portfolio_turnover

log = get_logger(__name__)


@dataclass(frozen=True)
class FollowPolicy:
    """실계좌가 System 목표를 따라갈 때의 결정적 규칙. 비중을 새로 정하지 않는다."""

    key: str = "system-follow"
    version: int = 1
    # System은 주 단위로 목표를 갱신한다. 그보다 오래된 목표는 System 엔진이 멈췄다는 뜻이라 따라가지 않는다.
    max_target_age_days: int = 10
    min_order_notional: float = ExecutionLimits().min_order_notional

    def to_config(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def hash(self) -> str:
        return hashlib.sha256(canonical_json(self.to_config()).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FollowOutcome:
    status: str  # "planned" | "skipped"
    reason: str | None
    target_id: str
    proposal_id: str | None = None
    risk_decision_id: str | None = None
    account_snapshot_id: str | None = None


def follow_weights(target_weights: Mapping[str, float], snapshot: AccountSnapshot) -> dict[str, float]:
    """System 목표비중 + 목표에 없는 보유 0. 실행 계층이 0인 종목을 전량 매도한다."""
    weights = {symbol: float(weight) for symbol, weight in validated_weights(target_weights).items()}
    for position in snapshot.positions:
        weights.setdefault(position.ticker, 0.0)
    return validated_weights(weights)


def order_gaps(weights: Mapping[str, float], snapshot: AccountSnapshot) -> dict[str, float]:
    """종목별 목표 금액 − 현재 금액(USD). 양수는 매수, 음수는 매도."""
    total = snapshot.total_value
    held = {position.ticker: position.market_value for position in snapshot.positions}
    return {
        symbol: float(weight) * total - held.get(symbol, 0.0)
        for symbol, weight in weights.items() if symbol != CASH_SYMBOL
    }


def plan_follow(
    repository: Any,
    *,
    target: Any,
    snapshot: AccountSnapshot,
    now: datetime,
    policy: FollowPolicy | None = None,
) -> FollowOutcome:
    """System 목표 하나와 새 계좌 스냅샷으로 실계좌 추종 제안·결정을 기록한다. 주문은 내지 않는다."""
    selected = policy or FollowPolicy()
    if not target.is_approved or not target.weights:
        raise ContractError("only an approved System target can be followed")
    if now - parse_datetime(target.decided_at) > timedelta(days=selected.max_target_age_days):
        return FollowOutcome("skipped", "system_target_stale", target.target_id)
    if snapshot.base_currency != "USD":
        raise ContractError("following an S&P 500 target requires a USD account snapshot")
    if snapshot.open_order_ids:
        return FollowOutcome("skipped", "account_has_open_orders", target.target_id)
    weights = follow_weights(target.weights, snapshot)
    gaps = order_gaps(weights, snapshot)
    if all(abs(value) < selected.min_order_notional for value in gaps.values()):
        return FollowOutcome("skipped", "already_following", target.target_id)

    decided_at = parse_datetime(snapshot.captured_at)
    run_id = stable_id("follow_run", {"target_id": target.target_id, "snapshot_id": snapshot.snapshot_id})
    account_snapshot_id = repository.save_portfolio_snapshot(snapshot)
    if account_snapshot_id is None:
        raise RuntimeError("execution account snapshot writer returned no snapshot id")
    repository.save_policy({
        "policy_key": selected.key, "policy_version": selected.version, "stage": "live",
        "model_provider": "deterministic_python", "model_name": "SystemFollow", "prompt_version": "none",
        "config": selected.to_config(),
    })
    repository.save_decision_run({
        "run_id": run_id, "as_of_at": decided_at.isoformat(), "stage": "live", "status": "running",
        "candidate_tickers": sorted(symbol for symbol in weights if symbol != CASH_SYMBOL),
        "account_snapshot_id": account_snapshot_id, "code_commit": None, "failure_reason": None,
    })
    proposal = PortfolioProposal.create(
        run_id=run_id, source_type="optimizer", source_version=f"system-follow:{target.target_id}", stage="live",
        as_of_at=decided_at.isoformat(), weights=weights, confidence=1.0,
        reasoning=("현재 System 목표비중을 그대로 따라가고, 목표에 없는 보유는 매도",),
        model_artifact_id=target.model_artifact_id,
        metadata={
            "coverage": "full_portfolio",
            "execution_eligible": True,
            "system_target_id": target.target_id,
            "system_proposal_id": target.proposal_id,
            "system_risk_decision_id": target.risk_decision_id,
            "snapshot_captured_at": snapshot.captured_at,
            "sold_outside_target": sorted(symbol for symbol, weight in weights.items()
                                          if symbol != CASH_SYMBOL and weight == 0.0),
            "order_gaps_usd": {symbol: round(value, 2) for symbol, value in sorted(gaps.items())},
        },
    )
    row = proposal.to_dict()
    row["account_snapshot_id"] = str(account_snapshot_id)
    repository.save_portfolio_proposal(row)
    input_hash = hashlib.sha256(canonical_json({
        "system_target_id": target.target_id, "system_risk_decision_id": target.risk_decision_id,
        "snapshot_id": snapshot.snapshot_id, "weights": weights,
    }).encode("utf-8")).hexdigest()
    decision = RiskDecision(
        risk_decision_id=stable_id("risk", {"proposal_id": proposal.proposal_id, "policy_hash": selected.hash,
                                            "input_hash": input_hash}),
        proposal_id=proposal.proposal_id, policy_key=selected.key, policy_version=selected.version,
        policy_hash=selected.hash, input_hash=input_hash, is_approved=True, approved_weights=weights,
        violations=(), adjustments=(),
        metrics={"system_target_id": target.target_id, "turnover": portfolio_turnover(snapshot.weights, weights)},
        decided_at=decided_at.isoformat(),
    )
    repository.save_risk_decision(decision.to_dict())
    identity = {"run_id": run_id, "proposal_id": proposal.proposal_id, "risk_decision_id": decision.risk_decision_id}
    repository.save_portfolio_decision({
        "decision_id": stable_id("decision", identity), **identity,
        "champion_policy": {"source_type": "system_follow", "system_target_id": target.target_id,
                            "automatic_promotion": False},
        "status": "approved",
    })
    repository.finish_decision_run(run_id, status="completed")
    log.info("my portfolio follow planned target=%s proposal=%s turnover=%.4f",
             target.target_id, proposal.proposal_id, decision.metrics["turnover"])
    return FollowOutcome("planned", None, target.target_id, proposal.proposal_id, decision.risk_decision_id,
                         str(account_snapshot_id))


__all__ = ["FollowOutcome", "FollowPolicy", "follow_weights", "order_gaps", "plan_follow"]
