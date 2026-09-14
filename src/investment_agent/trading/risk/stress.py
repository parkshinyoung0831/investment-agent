"""대표 ETF 충격을 보유 비중의 손실로 옮기는 결정론적 스트레스 시나리오.

## 왜 변동성·베타만으로는 부족한가

종목 여러 개를 나눠 담아도 사실상 같은 테마(기술주·금리 민감주)에 몰려 있으면, 변동성과 시장 베타는
괜찮아 보이는데 그 테마 하나가 무너질 때 계좌가 한꺼번에 빠진다. 시나리오마다 "그 충격에 이 종목이
얼마나 같이 움직였나"를 최근 이력으로 재고, 지금 비중에 곱해 손실을 본다.

## 추정 방법

시나리오마다 대표 ETF 하나에 대한 단일 회귀 민감도(β)를 쓴다. 여러 ETF를 한 번에 회귀하면 SPY·QQQ·
XLK처럼 서로 거의 같이 움직이는 설명변수 때문에 계수가 불안정해진다. 손실 = Σ 비중 × β × 충격.
충격 크기는 시나리오 정의(카탈로그)이고 한도는 `PortfolioRiskPolicy`가 소유한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL
from investment_agent.trading.portfolio.market_risk import estimate_betas


@dataclass(frozen=True)
class StressScenario:
    name: str
    proxy: str
    shock: float
    description: str


# 충격 크기는 과거 급락 구간에서 흔히 관측된 폭의 초기 정의다. 결과 분포가 쌓이면 원장에서 다시 본다.
STRESS_SCENARIOS: tuple[StressScenario, ...] = (
    StressScenario("market_down_10", "SPY", -0.10, "미국 대형주 시장 -10%"),
    StressScenario("nasdaq_down_15", "QQQ", -0.15, "나스닥100 -15%"),
    StressScenario("tech_down_20", "XLK", -0.20, "기술 섹터 -20%"),
    StressScenario("small_caps_down_15", "IWM", -0.15, "소형주 -15%"),
    StressScenario("rates_up_100bp", "TLT", -0.16, "장기 국채 가격 -16%(금리 약 +100bp)"),
    StressScenario("commodity_spike_20", "DBC", 0.20, "원자재 +20%(유가 급등)"),
    StressScenario("financials_down_20", "XLF", -0.20, "금융 섹터 -20%"),
    StressScenario("energy_down_25", "XLE", -0.25, "에너지 섹터 -25%"),
)
STRESS_PROXIES = tuple(sorted({scenario.proxy for scenario in STRESS_SCENARIOS}))


def scenario_sensitivities(
    price_rows_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    symbols: Sequence[str],
    minimum_observations: int = 60,
) -> dict[str, dict[str, float]]:
    """시나리오 이름 → 종목 → 대표 ETF 민감도. 대표 ETF나 종목 이력이 없으면 `estimate_betas`가 실패한다."""
    wanted = tuple(sorted({str(symbol).upper() for symbol in symbols if str(symbol).upper() != CASH_SYMBOL}))
    result: dict[str, dict[str, float]] = {}
    for scenario in STRESS_SCENARIOS:
        result[scenario.name] = (
            estimate_betas(price_rows_by_symbol, symbols=wanted, benchmark_symbol=scenario.proxy,
                           minimum_observations=minimum_observations)
            if wanted else {}
        )
    return result


def scenario_losses(
    weights: Mapping[str, float],
    sensitivities: Mapping[str, Mapping[str, float]],
) -> dict[str, float]:
    """시나리오별 포트폴리오 손실(양수 = 손실). 민감도가 없는 보유 종목이 있으면 실패한다."""
    shocks = {scenario.name: scenario.shock for scenario in STRESS_SCENARIOS}
    losses: dict[str, float] = {}
    for name, betas in sensitivities.items():
        if name not in shocks:
            raise ContractError(f"unknown stress scenario: {name}")
        held = [symbol for symbol, weight in weights.items() if symbol != CASH_SYMBOL and weight > 0.0]
        missing = sorted(symbol for symbol in held if symbol not in betas)
        if missing:
            raise ContractError(f"stress sensitivities are missing for {name}: {missing}")
        pnl = math.fsum(float(weights[symbol]) * float(betas[symbol]) * shocks[name] for symbol in held)
        losses[name] = max(0.0, -pnl)
    return losses


__all__ = ["STRESS_PROXIES", "STRESS_SCENARIOS", "StressScenario", "scenario_losses", "scenario_sensitivities"]
