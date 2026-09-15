"""투자 정책을 화면용 bounded read model로 투영한다."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from investment_agent.trading.portfolio.optimizer import OptimizerPolicy
from investment_agent.trading.risk.gate import PortfolioRiskPolicy
from investment_agent.trading.decision.fusion import DEFAULT_COMPONENT_WEIGHTS


def build_fusion_policy_read_model() -> dict[str, Any]:
    """현재 signal fusion 정책을 변경 없이 직렬화한다."""

    return {
        "version": "signal-fusion-v1",
        "component_weights": dict(DEFAULT_COMPONENT_WEIGHTS),
        "rule": "확신도로 가중하고 모델 간 방향 차이는 불확실성으로 보존",
    }


def build_optimizer_policy_read_model() -> dict[str, Any]:
    """현재 optimizer 기본 정책을 변경 없이 직렬화한다."""

    return asdict(OptimizerPolicy())


def build_risk_policy_read_model() -> dict[str, Any]:
    """현재 portfolio risk 기본 한도를 변경 없이 직렬화한다."""

    return PortfolioRiskPolicy().to_config()


__all__ = [
    "build_fusion_policy_read_model",
    "build_optimizer_policy_read_model",
    "build_risk_policy_read_model",
]
