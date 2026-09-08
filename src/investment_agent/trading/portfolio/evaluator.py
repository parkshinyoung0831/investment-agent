"""목표 비중 경로의 비용 포함 포트폴리오 성과를 계산한다."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PortfolioMetrics:
    total_return: float
    benchmark_return: float
    excess_return: float
    max_drawdown: float
    annualized_volatility: float
    turnover: float
    transaction_cost: float

    def to_dict(self) -> dict[str, float]:
        return self.__dict__.copy()


def evaluate_returns(
    returns: Sequence[float],
    benchmark_returns: Sequence[float],
    *,
    turnovers: Sequence[float] = (),
    cost_rate: float = 0.001,
    periods_per_year: int = 252,
) -> PortfolioMetrics:
    if len(returns) != len(benchmark_returns) or not returns:
        raise ValueError("portfolio and benchmark returns must have equal non-zero length")
    if len(turnovers) not in {0, len(returns)}:
        raise ValueError("turnovers must be empty or match the return periods")
    if cost_rate < 0.0:
        raise ValueError("cost_rate must be non-negative")
    if periods_per_year < 1:
        raise ValueError("periods_per_year must be positive")
    gross_returns = [float(value) for value in returns]
    benchmarks = [float(value) for value in benchmark_returns]
    period_turnovers = (
        [float(value) for value in turnovers]
        if len(turnovers) > 0 else [0.0] * len(returns)
    )
    if not all(math.isfinite(value) and value > -1.0 for value in gross_returns + benchmarks):
        raise ValueError("returns must be finite and greater than -1")
    if not all(math.isfinite(value) and value >= 0.0 for value in period_turnovers):
        raise ValueError("turnovers must be finite and non-negative")

    turnover = math.fsum(period_turnovers)
    transaction_cost = 0.0
    value = 1.0
    peak = 1.0
    max_drawdown = 0.0
    net_returns: list[float] = []
    for gross_return, period_turnover in zip(gross_returns, period_turnovers):
        cost_fraction = period_turnover * cost_rate
        transaction_cost += value * cost_fraction
        net_return = gross_return - cost_fraction
        if net_return <= -1.0:
            raise ValueError("transaction costs make a period return less than or equal to -1")
        value *= 1.0 + net_return
        net_returns.append(net_return)
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)
    total_return = value - 1.0
    benchmark_value = math.prod(1.0 + benchmark for benchmark in benchmarks)
    mean = math.fsum(net_returns) / len(net_returns)
    variance = math.fsum((value - mean) ** 2 for value in net_returns) / max(1, len(net_returns) - 1)
    return PortfolioMetrics(
        total_return=total_return,
        benchmark_return=benchmark_value - 1.0,
        excess_return=total_return - (benchmark_value - 1.0),
        max_drawdown=max_drawdown,
        annualized_volatility=math.sqrt(variance * periods_per_year),
        turnover=turnover,
        transaction_cost=transaction_cost,
    )
