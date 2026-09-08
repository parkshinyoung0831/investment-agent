"""재무·컨센서스 기반 Fundamental Desk."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from investment_agent.trading.contracts import EvidenceBundle
from investment_agent.trading.decision.desks.base import clamp, domain_items, finite, make_signal, nested_metrics


def analyze_fundamental(
    bundle: EvidenceBundle,
    *,
    metrics: Mapping[str, Any] | None = None,
) -> Any:
    """성장·마진·estimate revision을 동일 AnalystSignal 계약으로 반환한다."""
    items = domain_items(bundle, {"fundamentals", "estimates", "segments"})
    values = nested_metrics(items)
    values.update({str(key): value for key, value in (metrics or {}).items() if finite(value) is not None})
    components: list[float] = []
    reasons: list[str] = []
    growth = finite(values.get("revenue_growth_yoy"))
    margin = finite(values.get("operating_margin", values.get("operating_margin_ttm")))
    revision_breadth = finite(values.get("revision_breadth_30d"))
    revision = finite(values.get("estimate_revision", values.get("surprise_eps_pct")))
    true_fcf = finite(values.get("true_fcf_margin_ttm", values.get("true_fcf_yield")))
    fcf = finite(values.get("fcf_growth"))
    if growth is not None:
        components.append(clamp(growth * 3.0))
        reasons.append(f"매출 성장 {growth:.2%}")
    if margin is not None:
        components.append(clamp(margin * 2.0))
        reasons.append(f"영업이익률 {margin:.2%}")
    if revision_breadth is not None:
        components.append(clamp(revision_breadth))
        reasons.append(f"30일 컨센서스 리비전 {revision_breadth:+.2f}")
    elif revision is not None:
        components.append(clamp(revision / 20.0))
        reasons.append(f"컨센서스 변화 {revision:.2%}")
    if true_fcf is not None:
        components.append(clamp(true_fcf * 2.5))
        reasons.append(f"SBC차감 FCF수익/마진 {true_fcf:.2%}")
    elif fcf is not None:
        components.append(clamp(fcf * 3.0))
        reasons.append(f"FCF 변화 {fcf:.2%}")
    direction = sum(components) / len(components) if components else 0.0
    confidence = min(1.0, 0.32 + 0.16 * len(components))
    return make_signal(
        bundle,
        domain="fundamental",
        direction=direction,
        confidence=confidence,
        expected_return=direction * 0.035 if components else None,
        reasoning=reasons or ("재무·컨센서스 근거 없음",),
        evidence_items=items,
        missing_data=() if components else ("fundamental/estimate numeric evidence unavailable",),
    )


__all__ = ["analyze_fundamental"]
