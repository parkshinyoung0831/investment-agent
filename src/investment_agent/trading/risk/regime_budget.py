"""시장 regime에 따라 위험 한도를 **조이기만** 하는 결정론적 정책.

기본 한도(`PortfolioRiskPolicy`)는 평상시 기준이다. 시장이 흔들릴 때 같은 한도를 유지하면
평소라면 괜찮았을 집중이 동시 하락으로 번진다. 그래서 regime이 나빠질수록 종목·섹터 상한을
낮추고 최소 현금을 올리며, 위기에는 신규 위험을 막는다.

규칙 두 가지:
- **절대 완화하지 않는다.** 결과는 항상 기본 정책과 같거나 더 엄격하다(`min`/`max`로 합친다).
  regime 판정이 틀려도 한도가 느슨해지는 방향으로는 틀릴 수 없다.
- **LLM·모델이 아니라 가격 이력이 정한다.** regime 입력은 판단 시점까지의 SPY 일봉뿐이다.

배율 숫자는 초기값이다. RiskDecision 원장에 쌓이는 stress 지표 분포로 다시 보정할 자리다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Mapping, Sequence

import numpy as np

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.trading.decision.contracts import MarketRegime
from investment_agent.trading.decision.regime import build_market_regime
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
REGIME_BUDGET_VERSION = "regime-risk-budget-v1"


def tighten_for_regime(policy: PortfolioRiskPolicy, regime: MarketRegime | None) -> PortfolioRiskPolicy:
    """regime을 반영한 정책. regime을 모르면 기본 정책 그대로다."""
    if regime is None:
        return policy
    limits = REGIME_LIMITS.get(regime.risk_state)
    if limits is None:
        raise ContractError(f"no risk budget is defined for regime {regime.risk_state}")
    tightened = limits != REGIME_LIMITS["NORMAL"]
    return replace(
        policy,
        # 정책 원장은 (key, version)이 같으면 새 설정을 무시한다. 조인 한도를 같은 key로 저장하면
        # 원장에는 평상시 한도만 남아 판단을 재현할 수 없으므로 regime을 key에 넣는다.
        key=f"{policy.key}:{regime.risk_state.lower()}" if tightened else policy.key,
        max_symbol_weight=min(policy.max_symbol_weight, policy.max_symbol_weight * limits.symbol_weight_multiplier),
        max_sector_weight=min(policy.max_sector_weight, policy.max_sector_weight * limits.sector_weight_multiplier),
        min_cash_weight=max(policy.min_cash_weight, limits.min_cash_weight),
        allow_risk_increase=policy.allow_risk_increase and limits.allow_risk_increase,
    )


def regime_from_benchmark_prices(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of_at: datetime | str,
    minimum_observations: int = 60,
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
        if trade_date <= as_of.date() and math.isfinite(close) and close > 0:
            closes[trade_date] = close
    ordered = np.asarray([closes[key] for key in sorted(closes)], dtype=float)
    if len(ordered) < minimum_observations + 1:
        raise ContractError("insufficient benchmark history for a market regime")
    returns = ordered[1:] / ordered[:-1] - 1.0
    window = ordered[-252:]
    return build_market_regime(
        as_of.isoformat(),
        benchmark_return=float(ordered[-1] / ordered[-21] - 1.0),
        # 최근 20거래일 실현 변동성을 연율화한다. regime 경계(0.30·0.50)가 연율 기준이다.
        volatility=float(np.std(returns[-20:], ddof=1) * math.sqrt(252)),
        drawdown=float(1.0 - ordered[-1] / np.max(window)),
        source_ids=(f"benchmark_prices:{sorted(closes)[-1].isoformat()}",),
    )


__all__ = [
    "REGIME_BUDGET_VERSION",
    "REGIME_LIMITS",
    "RegimeLimits",
    "regime_from_benchmark_prices",
    "tighten_for_regime",
]
