"""Event와 보조 social feature 기반 Event Desk."""
from __future__ import annotations

from collections.abc import Sequence

from investment_agent.trading.contracts import EvidenceBundle
from investment_agent.trading.decision.contracts import AnalystSignal, Event, EventFeatureSnapshot
from investment_agent.trading.decision.desks.base import clamp, make_signal


def analyze_event(
    bundle: EvidenceBundle,
    *,
    events: Sequence[Event] = (),
    feature_snapshot: EventFeatureSnapshot | None = None,
) -> AnalystSignal:
    """동일 사건 cluster를 한 번만 반영하고 social은 관심도 보조값으로 낮게 반영한다."""
    selected = tuple(event for event in events if event.ticker == bundle.ticker)
    weighted = [event.direction * event.importance * event.confidence for event in selected]
    if feature_snapshot is not None:
        weighted.append(
            0.25 * feature_snapshot.news_sentiment
            + 0.10 * feature_snapshot.social_sentiment
        )
    direction = clamp(sum(weighted) / len(weighted)) if weighted else 0.0
    high_impact = sum(event.importance >= 0.75 for event in selected)
    confidence = min(1.0, 0.35 + 0.10 * len(selected) + 0.08 * high_impact)
    reasons = tuple(
        f"{event.event_type} importance={event.importance:.2f} direction={event.direction:.2f}"
        for event in selected[:5]
    )
    event_evidence_ids = tuple(
        evidence_id
        for event in selected
        for evidence_id in event.evidence_ids
    )
    if feature_snapshot is not None and feature_snapshot.social_velocity > 0:
        reasons += (f"social velocity={feature_snapshot.social_velocity:.3f} (보조 signal)",)
    return make_signal(
        bundle,
        domain="event",
        direction=direction,
        confidence=confidence,
        expected_return=direction * 0.03 if selected else None,
        reasoning=reasons or ("시점 기준 구조화 event 없음",),
        evidence_items=tuple(
            item for item in bundle.evidence if item.evidence_id in {
                evidence_id for event in selected for evidence_id in event.evidence_ids
            }
        ),
        evidence_ids=event_evidence_ids or None,
        missing_data=() if selected else ("event intelligence unavailable",),
        warnings=("social data is supplementary sentiment/attention only",)
        if feature_snapshot is not None and feature_snapshot.social_velocity > 0 else (),
    )


__all__ = ["analyze_event"]
