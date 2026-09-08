"""가격·기술지표 기반 Market Desk."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from investment_agent.trading.contracts import EvidenceBundle
from investment_agent.trading.decision.desks.base import clamp, domain_items, finite, make_signal, nested_metrics


def analyze_market(
    bundle: EvidenceBundle,
    *,
    metrics: Mapping[str, Any] | None = None,
) -> Any:
    """RSI/MACD·모멘텀·거래량을 매수 명령이 아닌 방향성 desk signal로 변환한다."""
    items = domain_items(bundle, {"market", "technical"})
    values = nested_metrics(items)
    values.update({str(key): value for key, value in (metrics or {}).items() if finite(value) is not None})
    return_20d = finite(values.get("return_20d"))
    volume_ratio = finite(values.get("volume_ratio_20d"))
    rsi = finite(values.get("rsi14"))
    macd = finite(values.get("macd_spread_pct", values.get("macd")))
    components: list[float] = []
    reasons: list[str] = []
    if return_20d is not None:
        component = clamp(return_20d * 6.0)
        components.append(component)
        reasons.append(f"20일 수익률 {return_20d:.2%}")
    if volume_ratio is not None and volume_ratio > 0:
        # 거래량 자체는 방향이 없으므로 현재 모멘텀의 conviction만 강화한다.
        multiplier = min(1.0, max(0.0, abs(math.log(volume_ratio)) / 2.0))
        base = components[0] if components else 0.0
        components.append(base * multiplier)
        reasons.append(f"거래량 배수 {volume_ratio:.2f}")
    if rsi is not None:
        components.append(clamp((rsi - 50.0) / 35.0))
        reasons.append(f"RSI {rsi:.1f}")
    if macd is not None:
        components.append(clamp(macd * 100.0))
        reasons.append(f"MACD spread {macd:.3%}")
    direction = sum(components) / len(components) if components else 0.0
    confidence = min(1.0, 0.30 + 0.16 * len(components))
    missing = () if components else ("market/technical numeric evidence unavailable",)
    return make_signal(
        bundle,
        domain="market",
        direction=direction,
        confidence=confidence,
        expected_return=direction * 0.025 if components else None,
        reasoning=reasons or ("시장·기술 근거 없음",),
        evidence_items=items,
        missing_data=missing,
    )


__all__ = ["analyze_market"]
