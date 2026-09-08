"""Desk 충돌이 있을 때만 실행하는 구조화 Bull/Bear 반론 단계."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from investment_agent.trading.decision.contracts import AnalystSignal, Event, MarketRegime


@dataclass(frozen=True)
class DebatePolicy:
    """비용이 큰 토론을 호출할 결정론적 조건."""

    min_direction_dispersion: float = 0.75
    low_confidence: float = 0.55
    high_impact_event: float = 0.80
    expected_risk_conflict: float = 0.60

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class DebateDecision:
    """토론 실행 여부와 이유를 보존하는 입력 gate 결과."""

    required: bool
    reasons: tuple[str, ...]
    direction_dispersion: float
    mean_confidence: float
    high_impact_event: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def debate_needed(
    signals: Sequence[AnalystSignal],
    *,
    events: Sequence[Event] = (),
    regime: MarketRegime | None = None,
    thesis_conflict: bool = False,
    policy: DebatePolicy | None = None,
) -> DebateDecision:
    """direction 충돌·낮은 확신·고위험 사건일 때만 Deep Debate를 요구한다."""
    policy = policy or DebatePolicy()
    directions = [float(signal.direction) for signal in signals]
    dispersion = max(directions) - min(directions) if directions else 0.0
    mean_confidence = sum(signal.confidence for signal in signals) / len(signals) if signals else 0.0
    high_event = any(event.importance >= policy.high_impact_event for event in events)
    reasons: list[str] = []
    if dispersion >= policy.min_direction_dispersion:
        reasons.append(f"desk direction dispersion={dispersion:.3f}")
    if mean_confidence < policy.low_confidence:
        reasons.append(f"desk confidence={mean_confidence:.3f}")
    if high_event:
        reasons.append("high-impact event present")
    if thesis_conflict:
        reasons.append("new event conflicts with existing thesis")
    if regime is not None and regime.risk_state in {"RISK_OFF", "CRISIS"}:
        positive = sum(signal.direction > 0.25 for signal in signals)
        if positive and regime.event_risk >= policy.expected_risk_conflict:
            reasons.append("positive desk view conflicts with risk-off regime/event risk")
    return DebateDecision(
        required=bool(reasons),
        reasons=tuple(reasons),
        direction_dispersion=dispersion,
        mean_confidence=mean_confidence,
        high_impact_event=high_event,
    )


def run_conditional_debate(
    signals: Sequence[AnalystSignal],
    *,
    events: Sequence[Event] = (),
    regime: MarketRegime | None = None,
    thesis_conflict: bool = False,
    policy: DebatePolicy | None = None,
) -> AnalystSignal | None:
    """LLM 자유문장 대신 desk의 찬성·반대 근거를 구조화 신호로 압축한다."""
    if not signals:
        return None
    decision = debate_needed(
        signals,
        events=events,
        regime=regime,
        thesis_conflict=thesis_conflict,
        policy=policy,
    )
    if not decision.required:
        return None
    ticker = signals[0].ticker
    as_of = signals[0].as_of_at
    if any(signal.ticker != ticker or signal.as_of_at != as_of for signal in signals):
        raise ValueError("debate signals must share ticker and as_of_at")
    denominator = sum(max(0.05, signal.confidence) for signal in signals)
    direction = sum(signal.direction * max(0.05, signal.confidence) for signal in signals) / denominator
    if regime is not None and regime.risk_state in {"RISK_OFF", "CRISIS"}:
        direction *= max(0.0, 1.0 - 0.25 * regime.event_risk)
    reasoning = (
        "조건부 Bull/Bear debate 실행",
        *decision.reasons,
        "bull/bear 반론은 자유 주문 문장이 아니라 AnalystSignal로 반환",
    )
    return AnalystSignal(
        ticker=ticker,
        as_of_at=as_of,
        domain="debate",
        direction=max(-1.0, min(1.0, direction)),
        score=max(-1.0, min(1.0, direction)),
        confidence=max(0.20, min(0.85, decision.mean_confidence * 0.85)),
        expected_return=direction * 0.025,
        horizon="5d",
        reasoning=reasoning,
        evidence_ids=tuple(sorted({evidence_id for signal in signals for evidence_id in signal.evidence_ids})),
        missing_data=tuple(sorted({item for signal in signals for item in signal.missing_data})),
        warnings=("debate output is advisory; portfolio and risk layers remain deterministic",),
        model="native-conditional-debate",
        version="native-debate-v1",
    )


__all__ = ["DebateDecision", "DebatePolicy", "debate_needed", "run_conditional_debate"]
