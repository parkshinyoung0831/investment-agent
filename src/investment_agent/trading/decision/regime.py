"""공통 시장 환경을 계산하는 결정론적 regime 모듈.

경계값(낙폭 8%·20%, 변동성 30%·50% 등)은 자연법칙이 아니라 정책값이다. `RegimeThresholds`에 버전과 함께
두어 연구(`research.ablation`)에서 과거 재현으로 다른 값과 비교할 수 있게 한다.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from investment_agent.trading.contracts import parse_datetime
from investment_agent.trading.decision.contracts import MarketRegime


@dataclass(frozen=True)
class RegimeThresholds:
    """regime 판정 경계. 값을 바꾸면 버전도 바꾼다 — 원장의 판단이 어떤 경계로 나왔는지 재현하기 위해서다."""

    version: str = "native-regime-v1"
    trend_up: float = 0.02
    trend_down: float = -0.02
    volatility_crisis: float = 0.50
    volatility_high: float = 0.30
    volatility_low: float = 0.12
    drawdown_crisis: float = 0.20
    drawdown_risk_off: float = 0.08
    breadth_risk_off: float = 0.35
    breadth_risk_on: float = 0.55
    event_risk_off: float = 0.85

    def __post_init__(self) -> None:
        if not 0 < self.drawdown_risk_off < self.drawdown_crisis < 1:
            raise ValueError("drawdown thresholds must satisfy 0 < risk_off < crisis < 1")
        if not 0 < self.volatility_low < self.volatility_high < self.volatility_crisis:
            raise ValueError("volatility thresholds must satisfy 0 < low < high < crisis")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_THRESHOLDS = RegimeThresholds()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _drawdown_fraction(value: float | None) -> float | None:
    if value is None:
        return None
    # 입력 provider에 따라 drawdown을 -0.12 또는 0.12로 표현할 수 있다.
    return _clamp(abs(value))


def build_market_regime(
    as_of_at: str | datetime,
    *,
    benchmark_return: float | None = None,
    breadth: float | None = None,
    volatility: float | None = None,
    rates_change: float | None = None,
    macro_score: float | None = None,
    liquidity: float | None = None,
    event_risk: float | None = None,
    drawdown: float | None = None,
    dispersion: float | None = None,
    available_at: str | datetime | None = None,
    source_ids: Iterable[str] = (),
    thresholds: RegimeThresholds = DEFAULT_THRESHOLDS,
) -> MarketRegime:
    """SPY·breadth·변동성·금리·macro·유동성 입력을 하나의 regime으로 압축한다."""
    limits = thresholds
    as_of = parse_datetime(as_of_at).astimezone(timezone.utc)
    available = parse_datetime(available_at or as_of).astimezone(timezone.utc)
    if available > as_of:
        raise ValueError("market regime available_at cannot be after as_of_at")
    values = {
        "benchmark_return": _number(benchmark_return),
        "breadth": _number(breadth),
        "volatility": _number(volatility),
        "rates_change": _number(rates_change),
        "macro_score": _number(macro_score),
        "liquidity": _number(liquidity),
        "event_risk": _number(event_risk),
        "drawdown": _drawdown_fraction(_number(drawdown)),
        "dispersion": _number(dispersion),
    }
    for name in ("breadth", "liquidity", "event_risk", "dispersion"):
        if values[name] is not None:
            values[name] = _clamp(values[name])
    if values["macro_score"] is not None:
        values["macro_score"] = max(-1.0, min(1.0, values["macro_score"]))

    benchmark = values["benchmark_return"]
    trend = "up" if benchmark is not None and benchmark > limits.trend_up else (
        "down" if benchmark is not None and benchmark < limits.trend_down else "sideways"
    )
    volatility_value = values["volatility"]
    volatility_state = (
        "crisis" if volatility_value is not None and volatility_value >= limits.volatility_crisis
        else "high" if volatility_value is not None and volatility_value >= limits.volatility_high
        else "low" if volatility_value is not None and volatility_value <= limits.volatility_low
        else "normal"
    )
    liquidity_value = values["liquidity"]
    liquidity_state = (
        "stressed" if liquidity_value is not None and liquidity_value < 0.20
        else "thin" if liquidity_value is not None and liquidity_value < 0.45
        else "deep" if liquidity_value is not None and liquidity_value >= 0.75
        else "normal"
    )
    macro_value = values["macro_score"]
    macro_state = (
        "supportive" if macro_value is not None and macro_value >= 0.25
        else "adverse" if macro_value is not None and macro_value <= -0.25
        else "neutral" if macro_value is not None else "unknown"
    )
    breadth_value = values["breadth"]
    drawdown_value = values["drawdown"] or 0.0
    event_value = values["event_risk"] or 0.0
    crisis = (
        drawdown_value >= limits.drawdown_crisis
        or volatility_state == "crisis"
        or liquidity_state == "stressed"
    )
    risk_off = (
        drawdown_value >= limits.drawdown_risk_off
        or volatility_state == "high"
        or (breadth_value is not None and breadth_value < limits.breadth_risk_off)
        or event_value >= limits.event_risk_off
        or macro_state == "adverse"
    )
    risk_on = (
        not risk_off
        and trend == "up"
        and (breadth_value is None or breadth_value >= limits.breadth_risk_on)
        and volatility_state in {"low", "normal"}
        and liquidity_state in {"deep", "normal"}
    )
    risk_state = "CRISIS" if crisis else "RISK_OFF" if risk_off else "RISK_ON" if risk_on else "NORMAL"
    present = sum(value is not None for value in values.values())
    confidence = _clamp(0.35 + 0.65 * present / len(values))
    if values["dispersion"] is not None and values["dispersion"] > 0.75:
        confidence *= 0.9
    metadata = {
        "inputs": values,
        "calculation": limits.version,
        "thresholds": limits.to_dict(),
        "dispersion_warning": bool(values["dispersion"] is not None and values["dispersion"] > 0.75),
    }
    return MarketRegime(
        as_of_at=as_of.isoformat(),
        risk_state=risk_state,
        trend=trend,
        volatility_state=volatility_state,
        liquidity_state=liquidity_state,
        macro_state=macro_state,
        event_risk=event_value,
        confidence=confidence,
        available_at=available.isoformat(),
        source_ids=tuple(str(item).strip() for item in source_ids if str(item).strip()),
        metadata=metadata,
    )


class MarketRegimeCalculator:
    """동일한 계산 계약을 반복 실행할 수 있게 하는 얇은 호출 객체."""

    version = "native-regime-v1"

    def calculate(self, as_of_at: str | datetime, **inputs: Any) -> MarketRegime:
        return build_market_regime(as_of_at, **inputs)


__all__ = ["DEFAULT_THRESHOLDS", "MarketRegimeCalculator", "RegimeThresholds", "build_market_regime"]
