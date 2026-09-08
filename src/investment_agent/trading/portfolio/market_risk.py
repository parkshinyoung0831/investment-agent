"""시점 고정 일별 가격으로 포트폴리오 시장 위험을 계산한다."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

import numpy as np

from investment_agent.trading.contracts import ContractError
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL, validated_weights


@dataclass(frozen=True)
class MarketRiskMetrics:
    """RiskGate가 소비하는 연율화 위험 측정치와 계산 근거다."""

    portfolio_volatility: float
    portfolio_beta: float
    max_pairwise_correlation: float
    drawdown_fraction: float
    observation_count: int
    first_trade_date: str
    last_trade_date: str
    benchmark_symbol: str

    def to_metadata(self) -> dict[str, object]:
        """RiskDecision 원장에 남길 계산 구간과 benchmark를 제공한다."""
        return {
            "observation_count": self.observation_count,
            "first_trade_date": self.first_trade_date,
            "last_trade_date": self.last_trade_date,
            "benchmark_symbol": self.benchmark_symbol,
        }


@dataclass(frozen=True)
class MarketCovariance:
    """Optimizer가 소비하는 같은 보유기간 기준 공분산 행렬과 계산 근거다."""

    symbols: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]
    horizon_days: int
    observation_count: int
    first_trade_date: str
    last_trade_date: str
    method: str
    input_hash: str

    def to_metadata(self) -> dict[str, object]:
        """제안 원장에 재현 가능한 행렬과 계산 방법·기간을 함께 남긴다."""
        return {
            "symbols": list(self.symbols),
            "matrix": [list(row) for row in self.matrix],
            "horizon_days": self.horizon_days,
            "observation_count": self.observation_count,
            "first_trade_date": self.first_trade_date,
            "last_trade_date": self.last_trade_date,
            "method": self.method,
            "input_hash": self.input_hash,
        }


def _close_by_date(rows: Sequence[Mapping[str, Any]], symbol: str) -> dict[date, float]:
    closes: dict[date, float] = {}
    for row in rows:
        try:
            trade_date = date.fromisoformat(str(row["trade_date"])[:10])
            close = float(row["close"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"{symbol} market price row is invalid") from exc
        if not math.isfinite(close) or close <= 0.0:
            raise ContractError(f"{symbol} market price close must be positive and finite")
        existing = closes.get(trade_date)
        if existing is not None and not math.isclose(existing, close, rel_tol=0.0, abs_tol=1e-10):
            raise ContractError(f"{symbol} has conflicting prices for {trade_date.isoformat()}")
        closes[trade_date] = close
    if len(closes) < 2:
        raise ContractError(f"{symbol} has insufficient market price history")
    return closes


def _aligned_returns(
    price_rows_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    symbols: Sequence[str],
    *,
    minimum_observations: int,
) -> tuple[tuple[str, ...], list[date], np.ndarray]:
    """지정 종목을 같은 거래일 수익률 행렬로 정렬한다."""
    normalized = tuple(str(symbol).upper().strip() for symbol in symbols)
    if not normalized or len(normalized) != len(set(normalized)) or CASH_SYMBOL in normalized:
        raise ContractError("covariance symbols must be unique risky assets")
    return_rows: dict[str, dict[date, float]] = {}
    for symbol in normalized:
        raw = price_rows_by_symbol.get(symbol)
        if not raw:
            raise ContractError(f"missing market price history: {symbol}")
        closes = _close_by_date(raw, symbol)
        ordered = sorted(closes.items())
        return_rows[symbol] = {
            current_date: (close / previous_close) - 1.0
            for (previous_date, previous_close), (current_date, close) in zip(ordered, ordered[1:])
            if current_date > previous_date
        }
    common_dates = sorted(set.intersection(*(set(values) for values in return_rows.values())))
    if len(common_dates) < minimum_observations:
        raise ContractError(
            f"insufficient aligned market return history: {len(common_dates)} < {minimum_observations}"
        )
    matrix = np.asarray(
        [[return_rows[symbol][trade_date] for symbol in normalized] for trade_date in common_dates],
        dtype=float,
    )
    if not np.isfinite(matrix).all():
        raise ContractError("market return history must be finite")
    return normalized, common_dates, matrix


def calculate_market_covariance(
    price_rows_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    symbols: Sequence[str],
    horizon_days: int,
    minimum_observations: int = 60,
) -> MarketCovariance:
    """기대수익 보유기간에 맞춘 point-in-time 표본 공분산을 계산한다."""
    if isinstance(horizon_days, bool) or horizon_days < 1:
        raise ValueError("horizon_days must be a positive integer")
    normalized, common_dates, asset_returns = _aligned_returns(
        price_rows_by_symbol,
        symbols,
        minimum_observations=minimum_observations,
    )
    if len(normalized) == 1:
        covariance = np.asarray([[float(np.var(asset_returns[:, 0], ddof=1))]], dtype=float)
    else:
        covariance = np.asarray(np.cov(asset_returns, rowvar=False, ddof=1), dtype=float)
    covariance *= horizon_days
    covariance = (covariance + covariance.T) / 2.0
    if covariance.shape != (len(normalized), len(normalized)) or not np.isfinite(covariance).all():
        raise ContractError("market covariance is invalid")
    minimum_eigenvalue = float(np.min(np.linalg.eigvalsh(covariance)))
    if minimum_eigenvalue < -1e-10:
        raise ContractError("market covariance is not positive semidefinite")
    if minimum_eigenvalue < 0.0:
        covariance += np.eye(len(normalized)) * (-minimum_eigenvalue)
    matrix = tuple(tuple(float(value) for value in row) for row in covariance)
    inputs = {
        "symbols": normalized,
        "horizon_days": horizon_days,
        "observation_count": len(common_dates),
        "first_trade_date": common_dates[0].isoformat(),
        "last_trade_date": common_dates[-1].isoformat(),
        "matrix": matrix,
    }
    return MarketCovariance(
        symbols=normalized,
        matrix=matrix,
        horizon_days=horizon_days,
        observation_count=len(common_dates),
        first_trade_date=common_dates[0].isoformat(),
        last_trade_date=common_dates[-1].isoformat(),
        method="sample_covariance",
        input_hash=hashlib.sha256(canonical_json(inputs).encode("utf-8")).hexdigest(),
    )


def calculate_market_risk(
    price_rows_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    target_weights: Mapping[str, float],
    benchmark_symbol: str = "SPY",
    minimum_observations: int = 60,
    annualization_days: int = 252,
) -> MarketRiskMetrics:
    """공통 거래일의 단순 수익률만 사용해 미래 가격과 결측 정렬을 차단한다."""
    if minimum_observations < 2 or annualization_days < 1:
        raise ValueError("minimum_observations must be >= 2 and annualization_days must be positive")
    weights = validated_weights(target_weights)
    symbols = tuple(sorted(symbol for symbol, weight in weights.items() if symbol != CASH_SYMBOL and weight > 0.0))
    benchmark = str(benchmark_symbol).upper().strip()
    if not benchmark:
        raise ValueError("benchmark_symbol is required")
    if not symbols:
        return MarketRiskMetrics(0.0, 0.0, 0.0, 0.0, 0, "", "", benchmark)

    required = tuple(dict.fromkeys((*symbols, benchmark)))
    aligned_symbols, common_dates, combined_returns = _aligned_returns(
        price_rows_by_symbol,
        required,
        minimum_observations=minimum_observations,
    )
    indexes = {symbol: index for index, symbol in enumerate(aligned_symbols)}
    asset_returns = combined_returns[:, [indexes[symbol] for symbol in symbols]]
    benchmark_returns = combined_returns[:, indexes[benchmark]]
    risky_weights = np.asarray([weights[symbol] for symbol in symbols], dtype=float)
    portfolio_returns = asset_returns @ risky_weights
    portfolio_volatility = float(np.std(portfolio_returns, ddof=1) * math.sqrt(annualization_days))
    benchmark_variance = float(np.var(benchmark_returns, ddof=1))
    if benchmark_variance <= 1e-12:
        raise ContractError("benchmark return variance is too small for beta")
    portfolio_beta = float(np.cov(portfolio_returns, benchmark_returns, ddof=1)[0, 1] / benchmark_variance)
    if len(symbols) == 1:
        max_pairwise_correlation = 0.0
    else:
        correlation = np.corrcoef(asset_returns, rowvar=False)
        upper = correlation[np.triu_indices(len(symbols), k=1)]
        if not np.isfinite(upper).all():
            raise ContractError("pairwise correlation is undefined for market return history")
        max_pairwise_correlation = float(np.max(upper))
    wealth = np.cumprod(1.0 + portfolio_returns)
    drawdown_fraction = float(np.max(1.0 - wealth / np.maximum.accumulate(wealth)))
    return MarketRiskMetrics(
        portfolio_volatility=portfolio_volatility,
        portfolio_beta=portfolio_beta,
        max_pairwise_correlation=max_pairwise_correlation,
        drawdown_fraction=drawdown_fraction,
        observation_count=len(common_dates),
        first_trade_date=common_dates[0].isoformat(),
        last_trade_date=common_dates[-1].isoformat(),
        benchmark_symbol=benchmark,
    )


__all__ = [
    "MarketCovariance", "MarketRiskMetrics", "calculate_market_covariance", "calculate_market_risk",
]
