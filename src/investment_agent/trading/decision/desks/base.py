"""Desk 구현이 공유하는 입력 추출·신호 생성 보조 함수."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from investment_agent.trading.contracts import EvidenceBundle
from investment_agent.trading.decision.contracts import AnalystSignal


def finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def clamp(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def domain_items(bundle: EvidenceBundle, domains: set[str]) -> tuple[Any, ...]:
    return tuple(item for item in bundle.evidence if item.domain in domains)


def nested_metrics(items: Sequence[Any]) -> dict[str, float]:
    """저장 payload의 흔한 통계 필드만 읽고 임의의 숫자를 만들지 않는다."""
    result: dict[str, float] = {}
    for item in items:
        payload = getattr(item, "payload", {})
        if not isinstance(payload, Mapping):
            continue
        candidates = [payload, payload.get("statistics"), payload.get("consensus_statistics")]
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            for key, value in candidate.items():
                parsed = finite(value)
                if parsed is not None:
                    result.setdefault(str(key), parsed)
    return result


def make_signal(
    bundle: EvidenceBundle,
    *,
    domain: str,
    direction: float,
    confidence: float,
    expected_return: float | None,
    reasoning: Sequence[str],
    evidence_items: Sequence[Any],
    evidence_ids: Sequence[str] | None = None,
    missing_data: Sequence[str] = (),
    warnings: Sequence[str] = (),
    model: str = "native-rule",
    version: str = "native-desk-v1",
) -> AnalystSignal:
    resolved_evidence_ids = (
        tuple(sorted({str(item).strip() for item in evidence_ids if str(item).strip()}))
        if evidence_ids is not None
        else tuple(sorted({str(item.evidence_id) for item in evidence_items}))
    )
    return AnalystSignal(
        ticker=bundle.ticker,
        as_of_at=bundle.as_of_at,
        domain=domain,
        direction=clamp(direction),
        score=clamp(direction),
        confidence=max(0.0, min(1.0, float(confidence))),
        expected_return=expected_return,
        horizon="5d",
        reasoning=tuple(str(item) for item in reasoning if str(item).strip()),
        evidence_ids=resolved_evidence_ids,
        missing_data=tuple(str(item) for item in missing_data if str(item).strip()),
        warnings=tuple(str(item) for item in warnings if str(item).strip()),
        model=model,
        version=version,
    )


__all__ = ["clamp", "domain_items", "finite", "make_signal", "nested_metrics"]
