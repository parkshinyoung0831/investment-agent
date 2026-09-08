"""금리·인플레이션·고용·경제일정 기반 Macro Desk."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from investment_agent.trading.contracts import EvidenceBundle
from investment_agent.trading.decision.desks.base import clamp, domain_items, finite, make_signal, nested_metrics


def analyze_macro(
    bundle: EvidenceBundle,
    *,
    metrics: Mapping[str, Any] | None = None,
) -> Any:
    """macro score와 event risk를 개별 종목 매수 명령으로 바꾸지 않는다."""
    items = domain_items(bundle, {"macro", "economic_calendar"})
    values = nested_metrics(items)
    values.update({str(key): value for key, value in (metrics or {}).items() if finite(value) is not None})
    components: list[float] = []
    reasons: list[str] = []
    for key, label, scale in (
        ("macro_score", "macro score", 1.0),
        ("rates_change", "금리 변화", -3.0),
        ("inflation_surprise", "인플레이션 surprise", -0.05),
        ("employment_surprise", "고용 surprise", 0.05),
    ):
        value = finite(values.get(key))
        if value is None:
            continue
        components.append(clamp(value * scale))
        reasons.append(f"{label} {value:.3f}")
    direction = sum(components) / len(components) if components else 0.0
    confidence = min(1.0, 0.30 + 0.16 * len(components))
    return make_signal(
        bundle,
        domain="macro",
        direction=direction,
        confidence=confidence,
        expected_return=direction * 0.015 if components else None,
        reasoning=reasons or ("macro·economic calendar 근거 없음",),
        evidence_items=items,
        missing_data=() if components else ("macro numeric evidence unavailable",),
    )


__all__ = ["analyze_macro"]
