"""목표 비중을 가격 이벤트 위에서 재생하는 결정론적 백테스트."""
from __future__ import annotations

from investment_agent.research.backtest.contracts import (
    BacktestConfig,
    BacktestRequest,
    BacktestResult,
    BacktestSafetyError,
    CorporateAction,
    MarketBar,
    UniverseSnapshot,
    WeightPoint,
)
from investment_agent.research.evaluation.costs import TransactionCostModel
from investment_agent.research.backtest.engine import WeightBacktestEngine, run_backtest
from investment_agent.research.backtest.metrics import BacktestMetrics

__all__ = [
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestRequest",
    "BacktestResult",
    "BacktestSafetyError",
    "CorporateAction",
    "MarketBar",
    "TransactionCostModel",
    "UniverseSnapshot",
    "WeightBacktestEngine",
    "WeightPoint",
    "run_backtest",
]
