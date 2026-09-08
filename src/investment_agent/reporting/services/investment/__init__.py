"""투자 판단을 Dashboard와 알림에 제공하는 제한된 read contract."""
from __future__ import annotations

from investment_agent.reporting.services.investment.decision_cases import (
    build_decision_case_read_model,
    build_decision_cases_read_model,
    normalize_role_analyses,
    summarize_role_analyses,
)
from investment_agent.reporting.services.investment.market_regime import build_live_regime_read_model
from investment_agent.reporting.services.investment.policy_snapshots import (
    build_fusion_policy_read_model,
    build_optimizer_policy_read_model,
    build_ranker_policy_read_model,
    build_risk_policy_read_model,
)

__all__ = [
    "build_decision_case_read_model",
    "build_decision_cases_read_model",
    "build_fusion_policy_read_model",
    "build_live_regime_read_model",
    "build_optimizer_policy_read_model",
    "build_ranker_policy_read_model",
    "build_risk_policy_read_model",
    "normalize_role_analyses",
    "summarize_role_analyses",
]
