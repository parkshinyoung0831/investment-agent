"""연구 metric과 OOS stability 평가."""
from __future__ import annotations

from investment_agent.research.evaluation.metrics import EvaluationScore, evaluate_predictions, is_stable_oos
from investment_agent.research.evaluation.challenger import (
    ChallengerComparison,
    ChallengerPolicy,
    compare_challenger,
)
from investment_agent.research.evaluation.costs import FillQuote, TransactionCostModel
from investment_agent.research.evaluation.deflated_sharpe import (
    DeflatedSharpeRatio,
    DeflatedSharpeResult,
)
from investment_agent.research.evaluation.shadow_fill import (
    ShadowTradeResult,
    round_trip_cost_rate,
    simulate_shadow_trade,
)

__all__ = [
    "ChallengerComparison",
    "ChallengerPolicy",
    "DeflatedSharpeRatio",
    "DeflatedSharpeResult",
    "EvaluationScore",
    "FillQuote",
    "ShadowTradeResult",
    "TransactionCostModel",
    "compare_challenger",
    "evaluate_predictions",
    "is_stable_oos",
    "round_trip_cost_rate",
    "simulate_shadow_trade",
]
