"""투자 정책을 화면용 bounded read model로 투영한다."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from investment_agent.trading.portfolio.optimizer import OptimizerPolicy
from investment_agent.trading.risk.gate import PortfolioRiskPolicy
from investment_agent.trading.decision.alpha import AlphaPolicy


def build_alpha_policy_read_model() -> dict[str, Any]:
    """현재 ALPHA 기대초과수익 정책을 변경 없이 직렬화한다."""

    return {
        **AlphaPolicy().to_dict(),
        "rule": "factor 사전값에 champion ML을 OOS 신뢰도만큼 결합하고 TradingAgents는 거부권·소폭 조정만 적용",
    }


def build_optimizer_policy_read_model() -> dict[str, Any]:
    """현재 optimizer 기본 정책을 변경 없이 직렬화한다."""

    return asdict(OptimizerPolicy())


def build_risk_policy_read_model() -> dict[str, Any]:
    """현재 portfolio risk 기본 한도를 변경 없이 직렬화한다."""

    return PortfolioRiskPolicy().to_config()


__all__ = [
    "build_alpha_policy_read_model",
    "build_optimizer_policy_read_model",
    "build_risk_policy_read_model",
]
