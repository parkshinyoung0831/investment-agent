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
from investment_agent.portfolio_weights import CASH_SYMBOL, validated_weights


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
    # 평소 변동성과 따로 보는 꼬리·스트레스 손실(양수 = 손실 비율). 한도로 쓰기 전에
    # 분포를 먼저 쌓아 보정해야 하므로 지금은 원장 기록용이다.
    historical_cvar_95_5d: float | None = None
    worst_5d_loss: float | None = None
    worst_20d_loss: float | None = None
    market_shock_loss: float | None = None
    market_shock: float = -0.10

    def to_metadata(self) -> dict[str, object]:
        """RiskDecision 원장에 남길 계산 구간과 benchmark를 제공한다."""
        return {
            "observation_count": self.observation_count,
            "first_trade_date": self.first_trade_date,
            "last_trade_date": self.last_trade_date,
            "benchmark_symbol": self.benchmark_symbol,
            "stress": {
                "historical_cvar_95_5d": self.historical_cvar_95_5d,
                "worst_5d_loss": self.worst_5d_loss,
                "worst_20d_loss": self.worst_20d_loss,
                "market_shock": self.market_shock,
                "market_shock_loss": self.market_shock_loss,
            },
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
    shrinkage: float = 0.0

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
            "shrinkage": self.shrinkage,
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
    closes_by_symbol: dict[str, dict[date, float]] = {}
    for symbol in normalized:
        raw = price_rows_by_symbol.get(symbol)
        if not raw:
            raise ContractError(f"missing market price history: {symbol}")
        closes_by_symbol[symbol] = _close_by_date(raw, symbol)
    # 시작일이 다른 이력은 겹치는 구간만 쓴다. 내부 결측은 채우거나 압축하지 않는다.
    # 종료일만 맞추면 이틀 수익률과 하루 수익률이 섞이고, 빈 구간을 버리면 CVaR의
    # '연속 5거래일' 의미까지 달라진다. 복구된 가격으로 재시도하기 전까지 차단한다.
    first = max(min(values) for values in closes_by_symbol.values())
    last = min(max(values) for values in closes_by_symbol.values())
    dates_by_symbol = {
        symbol: {day for day in values if first <= day <= last}
        for symbol, values in closes_by_symbol.items()
    }
    reference_dates = set.union(*dates_by_symbol.values())
    for symbol, dates in dates_by_symbol.items():
        missing = sorted(reference_dates - dates)
        if missing:
            raise ContractError(f"unaligned price intervals: {symbol} missing {missing[0].isoformat()}")
    price_dates = sorted(reference_dates)
    common_dates = price_dates[1:]
    if len(common_dates) < minimum_observations:
        raise ContractError(
            f"insufficient aligned market return history: {len(common_dates)} < {minimum_observations}"
        )
    matrix = np.asarray(
        [[closes_by_symbol[symbol][day] / closes_by_symbol[symbol][previous] - 1.0
          for symbol in normalized] for previous, day in zip(price_dates, price_dates[1:])],
        dtype=float,
    )
    if not np.isfinite(matrix).all():
        raise ContractError("market return history must be finite")
    return normalized, common_dates, matrix


def ledoit_wolf_constant_correlation(returns: np.ndarray) -> tuple[np.ndarray, float]:
    """표본 공분산을 '분산은 그대로, 상관은 평균 상관'인 prior 쪽으로 최적 강도만큼 당긴다.

    종목 수에 비해 관측일이 짧으면 표본 상관의 극단값이 대부분 추정 잡음이고, optimizer는
    그 잡음을 "헤지"로 오인해 비중을 몰아준다. prior를 단위행렬이 아니라 평균 상관으로 두는
    이유는 같은 방향으로 움직이는 주식 묶음의 공통 위험을 지우지 않기 위해서다
    (상관을 0으로 당기면 분산 효과가 과대평가된다). 강도는 Ledoit & Wolf(2003)의
    추정식이며 관측 행렬만으로 정해지므로 조정할 하이퍼파라미터가 없다.
    반환 행렬은 ddof=1 표본 공분산과 같은 스케일이다.
    """
    x = np.asarray(returns, dtype=float)
    t, n = x.shape
    if n < 2 or t < 2:
        raise ValueError("shrinkage requires at least two assets and two observations")
    x = x - x.mean(axis=0)
    sample = (x.T @ x) / t
    variance = np.diag(sample)
    if float(np.min(variance)) <= 1e-18:
        # 가격이 움직이지 않은 종목은 상관이 정의되지 않는다 — 표본 그대로 두고 강도 0을 남긴다.
        return sample * (t / (t - 1)), 0.0
    std = np.sqrt(variance)
    outer_std = np.outer(std, std)
    mean_correlation = float((np.sum(sample / outer_std) - n) / (n * (n - 1)))
    prior = mean_correlation * outer_std
    np.fill_diagonal(prior, variance)

    squared = x ** 2
    pi_matrix = (squared.T @ squared) / t - 2.0 * (x.T @ x) * sample / t + sample ** 2
    pi_hat = float(np.sum(pi_matrix))
    theta = ((x ** 3).T @ x) / t - variance[:, None] * sample
    np.fill_diagonal(theta, 0.0)
    rho_hat = float(np.sum(np.diag(pi_matrix))) + mean_correlation * float(
        np.sum((std[None, :] / std[:, None]) * theta)
    )
    gamma_hat = float(np.linalg.norm(sample - prior, "fro") ** 2)
    shrinkage = 0.0 if gamma_hat <= 1e-24 else max(0.0, min(1.0, (pi_hat - rho_hat) / gamma_hat / t))
    shrunk = shrinkage * prior + (1.0 - shrinkage) * sample
    return shrunk * (t / (t - 1)), float(shrinkage)


def calculate_market_covariance(
    price_rows_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    symbols: Sequence[str],
    horizon_days: int,
    minimum_observations: int = 60,
) -> MarketCovariance:
    """기대수익 보유기간에 맞춘 point-in-time 수축 공분산을 계산한다."""
    if isinstance(horizon_days, bool) or horizon_days < 1:
        raise ValueError("horizon_days must be a positive integer")
    normalized, common_dates, asset_returns = _aligned_returns(
        price_rows_by_symbol,
        symbols,
        minimum_observations=minimum_observations,
    )
    shrinkage = 0.0
    if len(normalized) == 1:
        covariance = np.asarray([[float(np.var(asset_returns[:, 0], ddof=1))]], dtype=float)
    else:
        covariance, shrinkage = ledoit_wolf_constant_correlation(asset_returns)
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
        method="sample_covariance" if len(normalized) == 1 else "ledoit_wolf_constant_correlation",
        input_hash=hashlib.sha256(canonical_json(inputs).encode("utf-8")).hexdigest(),
        shrinkage=round(shrinkage, 12),
    )


@dataclass(frozen=True)
class TradingCostInputs:
    """optimizer가 거래 **전에** 비용을 뺄 수 있도록 종목별로 추정한 편도 반스프레드.

    따라가는 실계좌가 수천 달러 규모라 주문이 시장 거래대금에 비해 무시할 만큼 작다. 그래서 시장충격·거래대금
    참여 한도는 두지 않고, 거래대금은 반스프레드 구간을 고르는 데만 쓴다.
    """

    symbol: str
    half_spread: float
    adv_usd: float
    method: str = "adv_bucket_half_spread_v2"

    def to_metadata(self) -> dict[str, object]:
        return {
            "half_spread": self.half_spread,
            "adv_usd": self.adv_usd,
            "method": self.method,
        }


# 호가 이력이 없어 반스프레드는 거래대금 구간으로 근사한다. S&P 500 대형주 실측 범위
# (1~10bp)의 보수적인 쪽이다. 실측 호가가 없는 종목은 이 보수적 근사를 유지한다.
_HALF_SPREAD_BY_ADV = ((1_000_000_000.0, 0.0001), (100_000_000.0, 0.0003), (0.0, 0.0010))


def estimate_trading_costs(
    price_rows_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    symbols: Sequence[str],
    adv_window: int = 20,
) -> dict[str, TradingCostInputs]:
    """point-in-time 일봉만으로 20일 평균 거래대금과 반스프레드를 추정한다."""
    result: dict[str, TradingCostInputs] = {}
    for raw_symbol in symbols:
        symbol = str(raw_symbol).upper().strip()
        rows = price_rows_by_symbol.get(symbol) or ()
        ordered = []
        for row in rows:
            try:
                ordered.append((
                    str(row["trade_date"])[:10], float(row["close"]), float(row.get("volume") or 0.0),
                ))
            except (KeyError, TypeError, ValueError) as exc:
                raise ContractError(f"{symbol} market price row is invalid") from exc
        ordered.sort()
        if len(ordered) < max(adv_window, 2) + 1:
            raise ContractError(f"{symbol} has insufficient history for trading cost estimates")
        dollar_volume = [close * volume for _, close, volume in ordered[-adv_window:]]
        adv_usd = float(np.mean(dollar_volume))
        if not math.isfinite(adv_usd) or adv_usd <= 0.0:
            raise ContractError(f"{symbol} has no usable dollar volume")
        half_spread = next(spread for floor, spread in _HALF_SPREAD_BY_ADV if adv_usd >= floor)
        result[symbol] = TradingCostInputs(symbol, half_spread, adv_usd)
    return result


def estimate_betas(
    price_rows_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    symbols: Sequence[str],
    benchmark_symbol: str = "SPY",
    minimum_observations: int = 60,
) -> dict[str, float]:
    """종목별 시장 베타. 같은 거래일 수익률로만 추정한다(결측일을 채우지 않는다)."""
    benchmark = str(benchmark_symbol).upper()
    result: dict[str, float] = {}
    for raw_symbol in symbols:
        symbol = str(raw_symbol).upper().strip()
        if symbol == benchmark:
            result[symbol] = 1.0
            continue
        _, _, matrix = _aligned_returns(
            price_rows_by_symbol, (symbol, benchmark), minimum_observations=minimum_observations,
        )
        variance = float(np.var(matrix[:, 1], ddof=1))
        if variance <= 1e-12:
            raise ContractError("benchmark return variance is too small for beta")
        result[symbol] = float(np.cov(matrix[:, 0], matrix[:, 1], ddof=1)[0, 1] / variance)
    return result


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
    wealth = np.concatenate(([1.0], np.cumprod(1.0 + portfolio_returns)))
    drawdown_fraction = float(np.max(1.0 - wealth / np.maximum.accumulate(wealth)))
    tail = historical_tail_losses(portfolio_returns)
    return MarketRiskMetrics(
        portfolio_volatility=portfolio_volatility,
        portfolio_beta=portfolio_beta,
        max_pairwise_correlation=max_pairwise_correlation,
        drawdown_fraction=drawdown_fraction,
        observation_count=len(common_dates),
        first_trade_date=common_dates[0].isoformat(),
        last_trade_date=common_dates[-1].isoformat(),
        benchmark_symbol=benchmark,
        historical_cvar_95_5d=tail["historical_cvar_95_5d"],
        worst_5d_loss=tail["worst_5d_loss"],
        worst_20d_loss=tail["worst_20d_loss"],
        # 단일 요인 충격: 시장이 10% 빠질 때 베타만큼 따라 빠진다고 본다.
        market_shock_loss=max(0.0, -portfolio_beta * -0.10) if math.isfinite(portfolio_beta) else None,
    )


def historical_tail_losses(daily_returns: Sequence[float] | np.ndarray) -> dict[str, float | None]:
    """겹치는 5·20거래일 누적수익으로 과거 최악 구간과 5일 CVaR95를 계산한다.

    변동성은 좌우 대칭으로 위험을 보지만, 계좌를 망가뜨리는 것은 한쪽 꼬리다. 최근 약 1년
    창에서 실제로 있었던 연속 손실을 지금 비중에 그대로 적용해 본다.
    """
    returns = np.asarray(daily_returns, dtype=float)
    if returns.ndim != 1 or not np.isfinite(returns).all():
        raise ContractError("tail loss inputs must be a finite 1-D return series")
    wealth = np.concatenate(([1.0], np.cumprod(1.0 + returns)))

    def window_returns(days: int) -> np.ndarray | None:
        if len(wealth) <= days:
            return None
        return wealth[days:] / wealth[:-days] - 1.0

    five = window_returns(5)
    twenty = window_returns(20)
    cvar = None
    if five is not None:
        worst_count = max(1, int(math.floor(len(five) * 0.05)))
        cvar = float(max(0.0, -np.mean(np.sort(five)[:worst_count])))
    return {
        "historical_cvar_95_5d": cvar,
        "worst_5d_loss": float(max(0.0, -np.min(five))) if five is not None else None,
        "worst_20d_loss": float(max(0.0, -np.min(twenty))) if twenty is not None else None,
    }


__all__ = [
    "MarketCovariance", "MarketRiskMetrics", "calculate_market_covariance", "calculate_market_risk",
    "ledoit_wolf_constant_correlation", "TradingCostInputs", "estimate_trading_costs", "historical_tail_losses",
    "estimate_betas",
]
