"""시장 regime에 따라 위험 한도를 **조이기만** 하는 결정론적 정책.

기본 한도(`PortfolioRiskPolicy`)는 평상시 기준이다. 시장이 흔들릴 때 같은 한도를 유지하면
평소라면 괜찮았을 집중이 동시 하락으로 번진다. 그래서 regime이 나빠질수록 종목·섹터 상한을
낮추고 최소 현금을 올리며, 위기에는 신규 위험을 막는다.

규칙 두 가지:
- **절대 완화하지 않는다.** 결과는 항상 기본 정책과 같거나 더 엄격하다(`min`/`max`로 합친다).
  regime 판정이 틀려도 한도가 느슨해지는 방향으로는 틀릴 수 없다.
- **LLM·모델이 아니라 가격 이력이 정한다.** regime 입력은 판단 시점까지의 SPY 일봉뿐이다.

배율·경계·기간은 정책값이다. `MarketRiskPolicy` 하나에 버전과 함께 모아 두고, 연구의 과거 재현
(`research.system_validation.ablation`)에서 다른 값과 비교한다.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from typing import Any, Mapping, Sequence

import numpy as np

from investment_agent.data.market.domain.calendar import bar_available_at, completed_bar_cutoff
from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.trading.decision.contracts import MarketRegime
from investment_agent.trading.decision.regime import DEFAULT_THRESHOLDS, RegimeThresholds, build_market_regime
from investment_agent.trading.risk.gate import PortfolioRiskPolicy


@dataclass(frozen=True)
class RegimeLimits:
    symbol_weight_multiplier: float
    sector_weight_multiplier: float
    min_cash_weight: float
    allow_risk_increase: bool


REGIME_LIMITS: Mapping[str, RegimeLimits] = {
    "RISK_ON": RegimeLimits(1.0, 1.0, 0.0, True),
    "NORMAL": RegimeLimits(1.0, 1.0, 0.0, True),
    "RISK_OFF": RegimeLimits(0.8, 0.8, 0.15, True),
    "CRISIS": RegimeLimits(0.5, 0.6, 0.40, False),
}
REGIME_BUDGET_VERSION = "regime-risk-budget-v2"


@dataclass(frozen=True)
class MarketRiskPolicy:
    """시장 전체 위험 → 위험 예산. 종목을 고르지 않는다. 숫자를 바꾸면 `version`도 바꾼다."""

    version: str = REGIME_BUDGET_VERSION
    thresholds: RegimeThresholds = DEFAULT_THRESHOLDS
    limits: Mapping[str, RegimeLimits] = field(default_factory=lambda: dict(REGIME_LIMITS))
    # SPY 20거래일 수익률(추세)·20거래일 실현 변동성(연율)·252거래일 고점 대비 낙폭.
    trend_window: int = 20
    volatility_window: int = 20
    drawdown_window: int = 252
    minimum_observations: int = 60
    # 거래소 달력을 추측하지 않는 보수적 유효기간. 주말+휴일을 허용하되 장기 정체는 차단한다.
    max_price_age_days: int = 4
    # 최소 현금을 계단 대신 변동성·낙폭의 연속 함수로 정한다(설계 §10.2). 계단 경계에서 현금이 0↔15↔40%로
    # 튀는 것을 없앤다. 종목·섹터 배율과 CRISIS의 신규 위험 금지는 그대로 계단이다 — 연속화는 현금 수준뿐이다.
    continuous_exposure: bool = False
    # 이 변동성(SPY 20일 실현, 연율)까지는 노출을 줄이지 않는다. 0.191은 2019-09~2026-09 SPY의 75백분위다.
    target_volatility: float = 0.191
    exposure_floor: float = 0.60

    def __post_init__(self) -> None:
        if set(self.limits) != set(REGIME_LIMITS):
            raise ValueError("market risk limits must define every regime state")
        if min(self.trend_window, self.volatility_window, self.drawdown_window, self.minimum_observations) < 2:
            raise ValueError("market risk windows must be at least 2")
        if isinstance(self.max_price_age_days, bool) or not isinstance(self.max_price_age_days, int) or self.max_price_age_days < 0:
            raise ValueError("max_price_age_days must be a non-negative integer")
        if not 0 < self.target_volatility < 1 or not 0 < self.exposure_floor <= 1:
            raise ValueError("target_volatility and exposure_floor must be in (0, 1)")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "limits": {state: asdict(limit) for state, limit in sorted(self.limits.items())}}


DEFAULT_MARKET_RISK_POLICY = MarketRiskPolicy()


def continuous_exposure(volatility: float | None, drawdown: float | None, *, policy: "MarketRiskPolicy") -> float:
    """위험자산 노출 상한 E* = min(E_vol, E_dd, 1). 입력이 없으면 그 축은 줄이지 않는다.

    E_vol = clip(σ*/σ, floor, 1)
    E_dd  = 1 (DD < 8%) → 0.85 (8%) → 0.70 (20%)로 선형, 20% 이상이면 floor
    낙폭 경계(8%·20%)는 regime 경계를 그대로 쓴다 — 새 경계를 만들지 않고 계단 사이를 잇는다.
    """
    thresholds = policy.thresholds
    exposure_vol = 1.0
    if volatility is not None and volatility > 0:
        exposure_vol = max(policy.exposure_floor, min(1.0, policy.target_volatility / volatility))
    exposure_dd = 1.0
    if drawdown is not None:
        dd = abs(float(drawdown))
        if dd >= thresholds.drawdown_crisis:
            exposure_dd = policy.exposure_floor
        elif dd >= thresholds.drawdown_risk_off:
            span = (dd - thresholds.drawdown_risk_off) / (thresholds.drawdown_crisis - thresholds.drawdown_risk_off)
            exposure_dd = max(policy.exposure_floor, 0.85 - 0.15 * span)
    return min(exposure_vol, exposure_dd)


def tighten_for_regime(
    policy: PortfolioRiskPolicy,
    regime: MarketRegime | None,
    market_policy: MarketRiskPolicy = DEFAULT_MARKET_RISK_POLICY,
) -> PortfolioRiskPolicy:
    """regime을 반영한 정책. regime을 모르면 기본 정책 그대로다."""
    if regime is None:
        return policy
    limits = market_policy.limits.get(regime.risk_state)
    if limits is None:
        raise ContractError(f"no risk budget is defined for regime {regime.risk_state}")
    min_cash = max(policy.min_cash_weight, _regime_cash(regime, limits, market_policy))
    tightened = limits != market_policy.limits["NORMAL"]
    key = f"{policy.key}:{regime.risk_state.lower()}" if tightened else policy.key
    if market_policy.continuous_exposure and min_cash > policy.min_cash_weight:
        # 연속 현금 하한은 값마다 다른 정책이다. key에 넣지 않으면 원장이 첫 값만 남긴다.
        key = f"{key}:cash{min_cash:.3f}"
    return replace(
        policy,
        # 정책 원장은 (key, version)이 같으면 새 설정을 무시한다. 조인 한도를 같은 key로 저장하면
        # 원장에는 평상시 한도만 남아 판단을 재현할 수 없으므로 regime을 key에 넣는다.
        key=key,
        max_symbol_weight=min(policy.max_symbol_weight, policy.max_symbol_weight * limits.symbol_weight_multiplier),
        max_sector_weight=min(policy.max_sector_weight, policy.max_sector_weight * limits.sector_weight_multiplier),
        min_cash_weight=min_cash,
        allow_risk_increase=policy.allow_risk_increase and limits.allow_risk_increase,
    )


def _regime_cash(regime: MarketRegime, limits: RegimeLimits, market_policy: MarketRiskPolicy) -> float:
    if not market_policy.continuous_exposure:
        return limits.min_cash_weight
    inputs = dict((regime.metadata or {}).get("inputs") or {})
    return 1.0 - continuous_exposure(inputs.get("volatility"), inputs.get("drawdown"), policy=market_policy)


def regime_from_benchmark_prices(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of_at: datetime | str,
    policy: MarketRiskPolicy = DEFAULT_MARKET_RISK_POLICY,
) -> MarketRegime:
    """판단 시점까지의 벤치마크 일봉만으로 추세·변동성·낙폭을 계산해 regime을 만든다."""
    as_of = parse_datetime(as_of_at)
    closes: dict[date, float] = {}
    for row in rows:
        try:
            trade_date = date.fromisoformat(str(row["trade_date"])[:10])
            close = float(row["close"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("benchmark price row is invalid") from exc
        if bar_available_at(trade_date, row.get("ingested_at")) > as_of:
            continue
        if not math.isfinite(close) or close <= 0:
            raise ContractError("benchmark close must be positive and finite")
        if trade_date in closes and not math.isclose(closes[trade_date], close, rel_tol=0.0, abs_tol=1e-10):
            raise ContractError(f"conflicting benchmark prices for {trade_date.isoformat()}")
        closes[trade_date] = close
    ordered = np.asarray([closes[key] for key in sorted(closes)], dtype=float)
    needed = max(policy.minimum_observations, policy.trend_window, policy.volatility_window) + 1
    if len(ordered) < needed:
        raise ContractError("insufficient benchmark history for a market regime")
    latest = max(closes)
    if (completed_bar_cutoff(as_of) - latest).days > policy.max_price_age_days:
        raise ContractError(f"stale benchmark history: last close {latest.isoformat()}")
    returns = ordered[1:] / ordered[:-1] - 1.0
    window = ordered[-policy.drawdown_window:]
    return build_market_regime(
        as_of.isoformat(),
        benchmark_return=float(ordered[-1] / ordered[-(policy.trend_window + 1)] - 1.0),
        # 실현 변동성을 연율화한다. regime 변동성 경계가 연율 기준이다.
        volatility=float(np.std(returns[-policy.volatility_window:], ddof=1) * math.sqrt(252)),
        drawdown=float(1.0 - ordered[-1] / np.max(window)),
        source_ids=(f"benchmark_prices:{sorted(closes)[-1].isoformat()}",),
        thresholds=policy.thresholds,
    )


__all__ = [
    "DEFAULT_MARKET_RISK_POLICY",
    "MarketRiskPolicy",
    "REGIME_BUDGET_VERSION",
    "REGIME_LIMITS",
    "RegimeLimits",
    "continuous_exposure",
    "regime_from_benchmark_prices",
    "tighten_for_regime",
]
