"""BACKTEST→SHADOW→PAPER→LIVE_MANUAL→LIVE_AUTONOMOUS 운영 승격 경계."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping

from investment_agent.platform.serialization import canonical_json


class LifecycleStage(str, Enum):
    BACKTEST = "backtest"
    SHADOW = "shadow"
    PAPER = "paper"
    LIVE_MANUAL = "live_manual"
    LIVE_AUTONOMOUS = "live_autonomous"


_NEXT = {
    LifecycleStage.BACKTEST: LifecycleStage.SHADOW,
    LifecycleStage.SHADOW: LifecycleStage.PAPER,
    LifecycleStage.PAPER: LifecycleStage.LIVE_MANUAL,
    LifecycleStage.LIVE_MANUAL: LifecycleStage.LIVE_AUTONOMOUS,
}


@dataclass(frozen=True)
class AutonomyEvidence:
    oos_days: int
    walk_forward_windows: int
    paper_days: int
    sharpe: float
    max_drawdown: float
    execution_errors: int
    reconciliation_errors: int
    risk_violations: int
    data_quality_incidents: int
    kill_switch_test_passed: bool
    broker_reconciliation_passed: bool


@dataclass(frozen=True)
class AutonomyCriteria:
    min_oos_days: int = 120
    min_walk_forward_windows: int = 6
    min_paper_days: int = 60
    min_sharpe: float = 0.5
    max_drawdown: float = 0.15


@dataclass(frozen=True)
class LifecycleDecision:
    from_stage: LifecycleStage
    to_stage: LifecycleStage
    is_approved: bool
    violations: tuple[str, ...]
    evidence_hash: str
    hard_limits: Mapping[str, float | int]


class LifecyclePromotionGate:
    """autonomy boolean만으로는 통과할 수 없는 결정적 증거 gate다."""

    def __init__(self, criteria: AutonomyCriteria | None = None):
        self.criteria = criteria or AutonomyCriteria()

    def evaluate(
        self,
        *,
        from_stage: LifecycleStage,
        to_stage: LifecycleStage,
        evidence: AutonomyEvidence,
        hard_limits: Mapping[str, float | int],
    ) -> LifecycleDecision:
        violations: list[str] = []
        if _NEXT.get(from_stage) != to_stage:
            violations.append("lifecycle promotion must advance exactly one stage")
        if to_stage == LifecycleStage.LIVE_AUTONOMOUS:
            if evidence.oos_days < self.criteria.min_oos_days:
                violations.append("out-of-sample evidence is too short")
            if evidence.walk_forward_windows < self.criteria.min_walk_forward_windows:
                violations.append("walk-forward evidence is too short")
            if evidence.paper_days < self.criteria.min_paper_days:
                violations.append("paper evidence is too short")
            if evidence.sharpe < self.criteria.min_sharpe:
                violations.append("risk-adjusted performance is below the autonomy threshold")
            if evidence.max_drawdown < -self.criteria.max_drawdown:
                violations.append("maximum drawdown exceeds the autonomy threshold")
            incidents = {
                "execution": evidence.execution_errors,
                "reconciliation": evidence.reconciliation_errors,
                "risk": evidence.risk_violations,
                "data_quality": evidence.data_quality_incidents,
            }
            violations.extend(f"{name} incident count is not zero" for name, count in incidents.items() if count)
            if not evidence.kill_switch_test_passed:
                violations.append("kill switch test has not passed")
            if not evidence.broker_reconciliation_passed:
                violations.append("broker reconciliation has not passed")
            required_limits = {
                "max_order_notional_usd", "max_daily_notional_usd", "max_daily_orders",
                "max_daily_loss_usd", "max_drawdown_fraction",
            }
            if not required_limits.issubset(hard_limits):
                violations.append("autonomy hard limits are incomplete")
        evidence_hash = hashlib.sha256(canonical_json({
            "evidence": asdict(evidence), "criteria": asdict(self.criteria),
            "hard_limits": dict(hard_limits),
        }).encode("utf-8")).hexdigest()
        return LifecycleDecision(
            from_stage=from_stage, to_stage=to_stage,
            is_approved=not violations, violations=tuple(violations),
            evidence_hash=evidence_hash, hard_limits=dict(hard_limits),
        )


__all__ = [
    "AutonomyCriteria", "AutonomyEvidence", "LifecycleDecision", "LifecyclePromotionGate",
    "LifecycleStage",
]
