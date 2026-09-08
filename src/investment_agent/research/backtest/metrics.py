"""백테스트 NAV·체결 장부에서 성과와 위험을 계산한다."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from investment_agent.research.backtest.contracts import FillEvent, NavPoint


@dataclass(frozen=True)
class BacktestMetrics:
    total_return: float
    cagr: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    turnover: float
    average_gross_exposure: float
    max_gross_exposure: float
    total_fees: float
    total_slippage: float
    dividend_income: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    trade_count: int
    win_rate: float
    transaction_cost: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sample_std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = math.fsum(values) / len(values)
    variance = math.fsum((item - mean) ** 2 for item in values) / (len(values) - 1)
    return math.sqrt(max(0.0, variance))


def calculate_metrics(
    nav_points: Sequence[NavPoint],
    fills: Sequence[FillEvent],
    *,
    initial_cash: float,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
) -> BacktestMetrics:
    """초기 현금을 첫 기준점으로 포함해 일별 수익과 비용 지표를 계산한다."""
    if not nav_points:
        raise ValueError("nav_points must not be empty")
    if initial_cash <= 0.0 or not math.isfinite(initial_cash):
        raise ValueError("initial_cash must be finite and positive")
    if periods_per_year < 1:
        raise ValueError("periods_per_year must be positive")
    values = [initial_cash, *(float(item.nav) for item in nav_points)]
    if any(not math.isfinite(value) or value <= 0.0 for value in values):
        raise ValueError("NAV values must be finite and positive")
    returns = [current / previous - 1.0 for previous, current in zip(values, values[1:])]
    total_return = values[-1] / values[0] - 1.0
    cagr = (values[-1] / values[0]) ** (periods_per_year / len(returns)) - 1.0

    peak = values[0]
    max_drawdown = 0.0
    for value in values[1:]:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)

    volatility = _sample_std(returns)
    annualized_volatility = volatility * math.sqrt(periods_per_year)
    period_risk_free = (1.0 + risk_free_rate) ** (1.0 / periods_per_year) - 1.0
    excess = [item - period_risk_free for item in returns]
    mean_excess = math.fsum(excess) / len(excess)
    sharpe = mean_excess / volatility * math.sqrt(periods_per_year) if volatility > 0.0 else 0.0
    downside_deviation = math.sqrt(
        math.fsum(min(0.0, item) ** 2 for item in excess) / len(excess)
    )
    sortino = (
        mean_excess / downside_deviation * math.sqrt(periods_per_year)
        if downside_deviation > 0.0 else 0.0
    )
    average_nav = math.fsum(item.nav for item in nav_points) / len(nav_points)
    turnover = math.fsum(item.gross_notional for item in fills) / average_nav
    exposures = [item.gross_exposure for item in nav_points]
    final = nav_points[-1]
    return BacktestMetrics(
        total_return=total_return,
        cagr=cagr,
        annualized_volatility=annualized_volatility,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=max_drawdown,
        turnover=turnover,
        average_gross_exposure=math.fsum(exposures) / len(exposures),
        max_gross_exposure=max(exposures),
        total_fees=math.fsum(item.fee for item in fills),
        total_slippage=math.fsum(item.slippage_cost for item in fills),
        dividend_income=final.dividends,
        realized_pnl=final.realized_pnl,
        unrealized_pnl=final.unrealized_pnl,
        total_pnl=final.total_pnl,
        trade_count=len(fills),
        win_rate=(
            math.fsum(1.0 for item in returns if item > 0.0) / len(returns)
            if returns else 0.0
        ),
        transaction_cost=(
            math.fsum(item.fee for item in fills)
            + math.fsum(item.slippage_cost for item in fills)
        ),
    )
