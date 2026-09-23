"""질문 레지스트리 — 무엇을 물을지는 코드가 아니라 여기가 소유한다.

질문을 호출부 문자열로 흩뿌리면 두 가지가 무너진다. 질문이 바뀐 것을 아무도 모르게 되고
(그러면 어제 답과 오늘 답을 같은 표에서 채점한다), provider끼리 **같은 질문**을 받았는지
보장할 수 없다(그러면 §48 비교가 성립하지 않는다).

버전 규칙: **질문 문구·보기·집합 구성이 바뀌면 version을 올린다.** 오타 수정도 마찬가지다 —
모델의 답은 문구에 민감하고, 우리는 그 민감도를 모른다.
"""
from __future__ import annotations

from investment_agent.trading.decision.judgment.contracts import (
    KIND_BOOLEAN,
    KIND_CHOICE,
    Question,
    QuestionSet,
)

# 실적·재무 사실에 대한 원자 질문. 숫자(factor/ML)가 이미 답하는 것은 묻지 않는다 —
# 판단 계층은 "숫자가 놓친 것"만 본다(§41).
FUNDAMENTAL_V1 = QuestionSet(
    name="fundamental",
    version=1,
    questions=(
        Question(
            question_id="thesis_broken",
            kind=KIND_BOOLEAN,
            prompt=(
                "이 회사의 투자 논지가 깨졌는가? 회계 부정, 핵심 사업의 구조적 훼손, "
                "존속 가능성을 위협하는 재무 상태처럼 **가격이 싸졌다고 해결되지 않는** 문제만 참이다."
            ),
            domains=("fundamentals", "segments"),
        ),
        Question(
            question_id="balance_sheet_deteriorating",
            kind=KIND_BOOLEAN,
            prompt="최근 공시에서 재무 건전성이 뚜렷하게 나빠지고 있는가(부채·이자보상·현금흐름)?",
            domains=("fundamentals",),
        ),
        Question(
            question_id="revenue_quality",
            kind=KIND_CHOICE,
            prompt="매출의 질은 어떤가? 일회성·회계 변경에 기댄 성장인지, 본업에서 나온 것인지.",
            choices=("organic", "mixed", "artificial", "unknown"),
            domains=("fundamentals", "segments"),
        ),
    ),
)

# 사건·뉴스 해석. 값이 아니라 **중대성**을 묻는다.
EVENT_V1 = QuestionSet(
    name="event",
    version=1,
    questions=(
        Question(
            question_id="material_news_present",
            kind=KIND_BOOLEAN,
            prompt="판단 시점 기준으로 주가에 중대한 영향을 줄 새 사건이 있는가?",
            domains=("news", "fundamentals"),
        ),
        Question(
            question_id="event_direction",
            kind=KIND_CHOICE,
            prompt="그 사건은 기업 가치에 어느 방향인가? 사건이 없으면 none이다.",
            choices=("positive", "negative", "ambiguous", "none"),
            domains=("news",),
        ),
    ),
)

# 라우터 전용. "이 종목에 비싼 판단을 쓸 가치가 있는가"만 묻는다(§47.3).
ROUTER_V1 = QuestionSet(
    name="router",
    version=1,
    questions=(
        Question(
            question_id="deep_reasoning_required",
            kind=KIND_BOOLEAN,
            prompt=(
                "이 종목은 깊은 추론(Multi-Agent 토론)이 필요한가? "
                "구조화된 근거만으로 방향이 분명하면 거짓이다."
            ),
            domains=("fundamentals", "news", "market"),
        ),
    ),
)

_REGISTRY: dict[str, QuestionSet] = {
    question_set.name: question_set
    for question_set in (FUNDAMENTAL_V1, EVENT_V1, ROUTER_V1)
}


def question_set(name: str) -> QuestionSet:
    """이름으로 질문묶음을 찾는다. 없는 이름은 조용히 빈 묶음이 되지 않고 실패한다."""
    try:
        return _REGISTRY[str(name)]
    except KeyError:
        raise KeyError(
            f"unknown question set: {name} (known: {sorted(_REGISTRY)})"
        ) from None


def registered_names() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


__all__ = [
    "EVENT_V1",
    "FUNDAMENTAL_V1",
    "ROUTER_V1",
    "question_set",
    "registered_names",
]
