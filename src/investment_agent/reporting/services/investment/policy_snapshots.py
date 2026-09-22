"""투자 정책을 화면용 bounded read model로 투영한다."""
from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from investment_agent.trading.portfolio.optimizer import OptimizerPolicy
from investment_agent.trading.risk.gate import PortfolioRiskPolicy
from investment_agent.trading.system.target import SystemPortfolioPolicy
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
    """현재 portfolio risk 기본 한도를 변경 없이 직렬화한다.

    CVaR 상한만은 맨몸 `PortfolioRiskPolicy()`를 쓰면 안 된다. 그 기본값은
    `max_cvar_95_5d=None`이라 변동성 상한에서 유도한 0.0872를 내놓지만, System
    파이프라인은 항상 `SystemPortfolioPolicy.max_cvar_95_5d`(0.08)를 주입한다
    (`trading/system/target.py`). 맨몸 값을 그대로 보여주면 화면이 **어떤 실행도
    쓰지 않는 한도**를 현재 한도라고 말한다 — 실제보다 0.7%p 느슨하게 보인다.

    나머지 한도는 regime·macro가 실행 시점에 조이므로 "기본 한도"가 맞는 표현이다.
    CVaR만 기본값 자체가 실제와 다르다.
    """
    effective = replace(
        PortfolioRiskPolicy(), max_cvar_95_5d=SystemPortfolioPolicy().max_cvar_95_5d,
    )
    return effective.to_config()


__all__ = [
    "build_alpha_policy_read_model",
    "build_optimizer_policy_read_model",
    "build_risk_policy_read_model",
]
