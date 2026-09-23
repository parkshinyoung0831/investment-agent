"""Escalation 라우터 — 비싼 판단을 **언제** 쓸지 정한다.

## 비용 레버는 모델 단가가 아니다

종목 하나의 Deep LLM 경로는 LLM 호출 14건이다. 모델을 6배 싼 것으로 바꿔도 14건을 다 하면
절감은 6배가 상한이지만, **호출 자체를 건너뛰면 그 종목의 비용은 0이다.** 그래서 단가보다
"이 종목에 깊은 판단이 필요한가"가 먼저다.

## 이 라우터는 fail-open이다

판단 근거가 없거나 provider가 답하지 못하면 **깊은 판단을 하는 쪽**으로 둔다.
게이트가 조용히 닫혀 분석이 통째로 빠지는 것이, 몇 번 더 부르는 것보다 나쁘다
(`CLAUDE.md`의 "시즌·조건 게이트는 fail-open" 원칙과 같다).

## 절감은 측정한 뒤에만 주장한다

`EscalationDecision`은 왜 그렇게 정했는지를 함께 들고, 회차 요약이 실제 건너뛴 비율을
남긴다. 그 숫자가 쌓이기 전에는 어떤 절감률도 문서에 적지 않는다(§50).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from investment_agent.platform.serialization import finite_float
from investment_agent.trading.decision.judgment.contracts import JudgmentResult

# 이 확률 미만으로 "깊은 판단이 필요 없다"고 말하면 믿지 않는다. 라우터가 틀려서 건너뛴
# 종목은 그날 아예 판단되지 않으므로, 건너뛰려면 꽤 확실해야 한다.
SKIP_CONFIDENCE_FLOOR = 0.60

REASON_NO_JUDGMENT = "no_structured_judgment"
REASON_ROUTER_SAYS_DEEP = "router_requires_deep_reasoning"
REASON_LOW_CONFIDENCE = "router_confidence_below_floor"
REASON_SIGNAL_DISAGREEMENT = "signal_disagreement"
REASON_HELD_POSITION = "held_position_always_reviewed"
REASON_SKIPPED = "structured_judgment_was_sufficient"


@dataclass(frozen=True)
class EscalationDecision:
    """이 종목에 Deep LLM을 쓸 것인가와 그 이유."""

    ticker: str
    escalate: bool
    reason: str
    confidence: float = 0.0
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "escalate": self.escalate,
            "reason": self.reason,
            "confidence": round(float(self.confidence), 6),
            **dict(self.detail),
        }


def decide_escalation(
    ticker: str,
    *,
    judgment: JudgmentResult | None,
    is_held: bool = False,
    factor_direction: float | None = None,
    ml_direction: float | None = None,
    confidence_floor: float = SKIP_CONFIDENCE_FLOOR,
) -> EscalationDecision:
    """깊은 판단이 필요한지 정한다. 건너뛸 이유가 분명할 때만 건너뛴다.

    - 보유 종목은 언제나 깊게 본다. 돈이 이미 들어가 있어 논지가 깨졌는지가 가장 급하고,
      그 판단을 아끼는 것은 절감이 아니라 위험이다.
    - factor와 ML이 반대 방향이면 숫자끼리 어긋난 것이다 — 해석이 필요하다.
    - 구조화 판단이 없거나 확신이 낮으면 올린다(fail-open).
    """
    symbol = str(ticker).upper().strip()
    if is_held:
        return EscalationDecision(symbol, True, REASON_HELD_POSITION, 1.0)

    factor = finite_float(factor_direction)
    ml = finite_float(ml_direction)
    if factor is not None and ml is not None and factor * ml < 0:
        return EscalationDecision(
            symbol, True, REASON_SIGNAL_DISAGREEMENT, 1.0,
            {"factor_direction": factor, "ml_direction": ml},
        )

    if judgment is None:
        return EscalationDecision(symbol, True, REASON_NO_JUDGMENT, 0.0)

    answer = judgment.answer("deep_reasoning_required")
    if answer is None:
        return EscalationDecision(
            symbol, True, REASON_NO_JUDGMENT, 0.0,
            {"unanswered": list(judgment.unanswered)},
        )
    if answer.value == "yes":
        return EscalationDecision(
            symbol, True, REASON_ROUTER_SAYS_DEEP, answer.confidence,
            {"probability": round(answer.probability, 6)},
        )
    if answer.confidence < float(confidence_floor):
        return EscalationDecision(
            symbol, True, REASON_LOW_CONFIDENCE, answer.confidence,
            {"floor": float(confidence_floor)},
        )
    return EscalationDecision(
        symbol, False, REASON_SKIPPED, answer.confidence,
        {"probability": round(answer.probability, 6)},
    )


def escalation_summary(decisions: Sequence[EscalationDecision]) -> dict[str, Any]:
    """회차의 escalation 비율. §50의 `escalation_rate`를 실제로 계산 가능하게 한다.

    분모가 0일 때 비율을 0으로 적지 않는다 — 아무것도 안 본 것과 전부 건너뛴 것은 다르다.
    """
    if not decisions:
        return {"scanned": 0}
    escalated = [item for item in decisions if item.escalate]
    reasons: dict[str, int] = {}
    for item in decisions:
        reasons[item.reason] = reasons.get(item.reason, 0) + 1
    return {
        "scanned": len(decisions),
        "escalated": len(escalated),
        "skipped": len(decisions) - len(escalated),
        "escalation_rate": round(len(escalated) / len(decisions), 4),
        "reasons": dict(sorted(reasons.items())),
    }


__all__ = [
    "EscalationDecision",
    "REASON_HELD_POSITION",
    "REASON_LOW_CONFIDENCE",
    "REASON_NO_JUDGMENT",
    "REASON_ROUTER_SAYS_DEEP",
    "REASON_SIGNAL_DISAGREEMENT",
    "REASON_SKIPPED",
    "SKIP_CONFIDENCE_FLOOR",
    "decide_escalation",
    "escalation_summary",
]
