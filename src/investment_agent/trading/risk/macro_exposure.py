"""거시 위험 신호로 전체 주식 노출 상한을 **낮추기만** 하는 결정론적 규칙.

시장 위험이 커질 때 종목을 더 잘 고르려 하기보다 전체 노출을 줄인다. 가격 regime(`regime_budget`)은 SPY
자체의 낙폭·변동성을 본다 — 이미 떨어진 뒤에야 켜진다. 여기서는 가격보다 먼저 움직이는 경향이 있는
신용·변동성·시장 폭을 본다.

| 신호 | 경계(caution) | 위험(stress) |
|---|---|---|
| HY OAS 수준 | ≥ 4.5% | ≥ 6.0% |
| HY OAS 63일 확대폭 | ≥ +0.75%p | ≥ +1.5%p |
| VIX | ≥ 25 | ≥ 32 |
| 200일선 상회 비율 | < 35% | < 20% |

위험 신호 수로 주식 노출 상한을 정한다: 경계만 있으면 90%, 위험 1개 75%, 2개 이상 55%. 결과는 최소 현금
비중으로 표현해 기존 정책과 `max`로 합친다 — 절대 완화하지 않는다.

- 판단일 **전날까지** 관측된 값만 쓴다. 시장 series는 수집 시각이 관측일 00:00으로 저장돼, 당일 값을 쓰면
  아직 끝나지 않은 날의 종가를 미리 보는 셈이 된다.
- 최신 관측이 10일보다 오래됐거나 없으면 그 신호는 판단하지 않는다(조이지도 않는다). 가격 regime이 여전히
  hard gate다. 웹 수집 장애 하루가 실계좌를 멈추게 두지 않는다.

경계값은 2000년 이후 HY OAS·VIX 분포의 상위 구간에서 잡은 초기값이다. RiskDecision 원장으로 다시 본다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from investment_agent.trading.risk.gate import PortfolioRiskPolicy

MACRO_EXPOSURE_VERSION = "macro-exposure-v1"
MACRO_SERIES = ("HY_SPREAD", "VIX", "BREADTH_200DMA")
_STALE_DAYS = 10
_CHANGE_LOOKBACK_DAYS = 63
EXPOSURE_CAPS = {0: 1.0, "caution": 0.90, 1: 0.75, 2: 0.55}


@dataclass(frozen=True)
class MacroExposureState:
    max_equity_exposure: float
    stress: tuple[str, ...]
    caution: tuple[str, ...]
    unavailable: tuple[str, ...]
    inputs: Mapping[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": MACRO_EXPOSURE_VERSION,
            "max_equity_exposure": self.max_equity_exposure,
            "stress": list(self.stress),
            "caution": list(self.caution),
            "unavailable": list(self.unavailable),
            "inputs": dict(self.inputs),
        }


def _usable(history: Sequence[tuple[date, float]], as_of: date) -> list[tuple[date, float]]:
    return sorted(
        (day, float(value)) for day, value in history
        if day < as_of and value is not None and math.isfinite(float(value))
    )


def assess_macro_exposure(histories: Mapping[str, Sequence[tuple[date, float]]], *, as_of_at: datetime) -> MacroExposureState:
    """series별 (관측일, 값) 이력으로 노출 상한을 정한다."""
    as_of = as_of_at.date()
    stress: list[str] = []
    caution: list[str] = []
    unavailable: list[str] = []
    inputs: dict[str, Any] = {}
    latest: dict[str, tuple[date, float]] = {}
    for series in MACRO_SERIES:
        rows = _usable(histories.get(series, ()), as_of)
        if not rows or (as_of - rows[-1][0]).days > _STALE_DAYS:
            unavailable.append(series)
            continue
        latest[series] = rows[-1]
        inputs[series] = {"obs_date": rows[-1][0].isoformat(), "value": rows[-1][1]}
        if series == "HY_SPREAD":
            base = [value for day, value in rows if day <= rows[-1][0] - timedelta(days=_CHANGE_LOOKBACK_DAYS)]
            if base:
                inputs[series]["change_63d"] = rows[-1][1] - base[-1]

    def grade(name: str, value: float, *, caution_at: float, stress_at: float, higher_is_worse: bool = True) -> None:
        worse = (lambda threshold: value >= threshold) if higher_is_worse else (lambda threshold: value < threshold)
        if worse(stress_at):
            stress.append(name)
        elif worse(caution_at):
            caution.append(name)

    if "HY_SPREAD" in latest:
        grade("credit_spread_level", latest["HY_SPREAD"][1], caution_at=4.5, stress_at=6.0)
        change = inputs["HY_SPREAD"].get("change_63d")
        if change is not None:
            grade("credit_spread_widening", change, caution_at=0.75, stress_at=1.5)
    if "VIX" in latest:
        grade("volatility", latest["VIX"][1], caution_at=25.0, stress_at=32.0)
    if "BREADTH_200DMA" in latest:
        grade("breadth", latest["BREADTH_200DMA"][1], caution_at=35.0, stress_at=20.0, higher_is_worse=False)

    if len(stress) >= 2:
        cap = EXPOSURE_CAPS[2]
    elif stress:
        cap = EXPOSURE_CAPS[1]
    elif caution:
        cap = EXPOSURE_CAPS["caution"]
    else:
        cap = EXPOSURE_CAPS[0]
    return MacroExposureState(cap, tuple(stress), tuple(caution), tuple(unavailable), inputs)


def tighten_for_macro(policy: PortfolioRiskPolicy, state: MacroExposureState | None) -> PortfolioRiskPolicy:
    """노출 상한을 최소 현금으로 바꿔 합친다. 상한이 100%거나 상태를 모르면 정책 그대로다."""
    if state is None or state.max_equity_exposure >= 1.0:
        return policy
    min_cash = max(policy.min_cash_weight, 1.0 - state.max_equity_exposure)
    if min_cash <= policy.min_cash_weight:
        return policy
    return replace(
        policy,
        # 조인 한도를 같은 key로 저장하면 정책 원장에 평상시 한도만 남는다(regime_budget과 같은 이유).
        key=f"{policy.key}:macro{int(round(state.max_equity_exposure * 100))}",
        min_cash_weight=min_cash,
    )


__all__ = [
    "EXPOSURE_CAPS",
    "MACRO_EXPOSURE_VERSION",
    "MACRO_SERIES",
    "MacroExposureState",
    "assess_macro_exposure",
    "tighten_for_macro",
]
