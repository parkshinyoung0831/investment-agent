"""결정론 판단 provider — 계산으로 답할 수 있는 질문은 모델에게 묻지 않는다.

`§42`의 원칙("가장 싼 단계에서 풀리는 문제는 그 단계에서 끝낸다")의 Level 0 구현이다.
비용 0, 지연 0, 재현 100%다. 이것이 답하지 못하는 질문만 위 단계로 올라간다.

## 확률을 어떻게 만드는가

규칙이 답을 알면 확률을 1.0으로 두지 않는다. **feature가 관측된 값이지 미래의 사실이 아니기
때문이다.** 부채비율이 높다는 것은 관측이고, "재무가 나빠지고 있다"는 그 관측의 해석이다.
그래서 규칙은 관측의 강도에 따라 0.5~0.9 사이의 확률을 주고, 근거가 없으면 **답하지 않는다**
(`unanswered`). 모르는 것을 0.5로 적으면 "반반이라고 판단했다"와 구별되지 않는다.
"""
from __future__ import annotations

import time
from typing import Any, Mapping

from investment_agent.platform.serialization import finite_float
from investment_agent.trading.decision.judgment.contracts import (
    Answer,
    JudgmentProvider,
    JudgmentResult,
    QuestionSet,
)

# 관측이 아주 뚜렷할 때 줄 수 있는 확률 상한. 결정론 규칙도 미래를 모른다.
_STRONG = 0.85
_MODERATE = 0.70


def _boolean(probability_true: float) -> dict[str, float]:
    probability = max(0.0, min(1.0, float(probability_true)))
    return {"yes": probability, "no": 1.0 - probability}


class DeterministicJudge(JudgmentProvider):
    """feature 값만으로 답할 수 있는 질문에 답한다. 나머지는 `unanswered`로 남긴다."""

    name = "deterministic"
    model = "rules-v1"

    def evaluate(
        self,
        state: Any,
        questions: QuestionSet,
        *,
        features: Mapping[str, Any] | None = None,
    ) -> JudgmentResult:
        started = time.monotonic()
        values = dict(features or {})
        answers: list[Answer] = []
        unanswered: list[str] = []
        for question in questions.questions:
            handler = getattr(self, f"_answer_{question.question_id}", None)
            distribution = handler(values) if handler is not None else None
            if distribution is None:
                unanswered.append(question.question_id)
                continue
            answers.append(Answer.from_distribution(question.question_id, distribution))
        return JudgmentResult(
            provider=self.name,
            model=self.model,
            question_set_key=questions.key,
            answers=tuple(answers),
            unanswered=tuple(unanswered),
            latency_ms=(time.monotonic() - started) * 1000.0,
            input_tokens=0,
            output_tokens=0,
        )

    # ---- 질문별 규칙 -----------------------------------------------------
    # 메서드 이름이 question_id와 같아야 연결된다. 이름이 어긋나면 그 질문은 조용히
    # 답 없음이 되므로 `test_every_answerable_question_has_a_rule`이 이름을 고정한다.

    @staticmethod
    def _answer_balance_sheet_deteriorating(values: Mapping[str, Any]) -> dict[str, float] | None:
        """부채비율과 이자보상배율의 조합. 둘 다 모르면 답하지 않는다."""
        debt = finite_float(values.get("quality_debt_to_equity"))
        coverage = finite_float(values.get("quality_interest_coverage_ttm"))
        if debt is None and coverage is None:
            return None
        # 이자보상 1 미만은 영업이익으로 이자도 못 갚는다는 뜻이라 가장 강한 신호다.
        if coverage is not None and coverage < 1.0:
            return _boolean(_STRONG)
        if debt is not None and debt > 3.0:
            return _boolean(_MODERATE)
        if coverage is not None and coverage > 5.0 and (debt is None or debt < 1.5):
            return _boolean(1.0 - _STRONG)
        return _boolean(1.0 - _MODERATE)

    @staticmethod
    def _answer_deep_reasoning_required(values: Mapping[str, Any]) -> dict[str, float] | None:
        """깊은 추론이 필요한가 — 라우터의 핵심 질문.

        근거가 서로 어긋나거나 새 사건이 있을 때만 비싼 단계로 보낸다. 방향이 한쪽으로
        분명하면 Multi-Agent 토론이 새로 알려 줄 것이 적다.
        """
        events = finite_float(values.get("event_high_impact_count"))
        momentum = finite_float(values.get("momentum_12_1"))
        revision = finite_float(values.get("revision_breadth_30d"))
        if events is None and momentum is None and revision is None:
            return None
        if events is not None and events > 0:
            return _boolean(_STRONG)  # 새 사건은 숫자가 아직 모르는 것이다
        if momentum is not None and revision is not None:
            # 모멘텀과 추정치 개정이 반대 방향이면 숫자끼리 싸우는 것이다 — 사람의 해석이 필요하다.
            if momentum * revision < 0 and abs(revision) > 0.2:
                return _boolean(_MODERATE)
            return _boolean(1.0 - _MODERATE)
        return None


__all__ = ["DeterministicJudge"]
