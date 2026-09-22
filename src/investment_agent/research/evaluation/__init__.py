"""연구 metric과 OOS 평가.

순위 상관(IC)은 `alpha.py`가 소유한다 — 날짜별 단면으로 계산해야 시장 전체가 오른 날의
공통 움직임이 순위 능력처럼 부풀지 않는다. 날짜를 섞어 한 번에 상관을 구하던
`metrics.py`(pooled, 동률을 고유값 dense rank로)는 쓰는 곳이 없어 지웠다 —
같은 이름(`rank_correlation`)을 다른 규칙으로 계산하는 사본이 하나 줄었다.
"""
from __future__ import annotations

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
    "FillQuote",
    "ShadowTradeResult",
    "TransactionCostModel",
    "compare_challenger",
    "round_trip_cost_rate",
    "simulate_shadow_trade",
]
