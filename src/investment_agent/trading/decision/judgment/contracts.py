"""구조화 판단(System-One)의 계약 — 질문 하나에 답 하나, 확률과 함께.

## 왜 LLMClient로는 안 되는가

`llm/client.py`의 `LLMClient`는 **대화형**이다(system/user 문자열 → JSON 객체). 그 모양은
"자유 서술을 시키고 결과를 JSON으로 받는다"는 뜻이고, 답이 얼마나 확실한지는 모델이
스스로 적은 숫자뿐이다 — `§18`이 쓰지 말라고 한 바로 그 값이다.

여기 계약은 다르다. **질문을 미리 정해 두고**(`QuestionSet`) 각 질문에 대해
답 + 확률분포 + 신뢰도를 받는다. 이 모양이어야:

- 같은 질문을 여러 provider(결정론 규칙 · 싼 LLM · Jev 같은 System-One 모델)에게
  똑같이 물어 비교할 수 있다.
- 답의 확률을 사후 결과와 대조해 **검증된 신뢰도**를 만들 수 있다(§18의 입력).
- 질문이 바뀌면 그것이 새 평가 artifact가 된다(§47.2, §14와 같은 불변성 원칙).

## 이것은 비중을 정하지 않는다

판단 계층은 "그 사실이 무엇을 의미하는가"에만 답한다(§41). 최종 비중·주문·hard limit은
여전히 Optimizer와 `trading/risk/gate.py`가 소유한다
(`SYSTEM_UPGRADE_MASTER.md` §4.2/§4.3, 절대 불변).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from investment_agent.platform.serialization import ContractError

# 질문이 요구하는 답의 종류. Jev의 primitive 이름을 그대로 쓰지 않는다 — 벤더 어휘를
# 계약에 넣으면 그 벤더가 architecture가 된다(§44).
KIND_BOOLEAN = "boolean"   # 예/아니오. 참일 확률 하나를 돌려준다.
KIND_CHOICE = "choice"     # 정해진 보기 중 하나 + 보기별 확률.
KIND_SCORE = "score"       # 순서 있는 등급 + 등급별 확률의 기대값.
KINDS = frozenset({KIND_BOOLEAN, KIND_CHOICE, KIND_SCORE})

# 한 질문이 가질 수 있는 보기 수 상한. 보기가 많아지면 확률이 흩어져 신뢰도가 무의미해지고,
# provider마다 상한이 달라 비교가 깨진다.
MAX_CHOICES = 32


@dataclass(frozen=True)
class Question:
    """판단 하나만 담당하는 질문. 거대한 단일 질문을 쓰지 않는다(§47.1)."""

    question_id: str
    kind: str
    prompt: str
    choices: tuple[str, ...] = ()
    # 이 질문이 읽어야 할 evidence 도메인. 라우터가 관련 없는 근거를 실어 보내지 않게 한다.
    domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.question_id).strip():
            raise ContractError("question_id is required")
        if self.kind not in KINDS:
            raise ContractError(f"unsupported question kind: {self.kind}")
        if not str(self.prompt).strip():
            raise ContractError(f"{self.question_id}: prompt is required")
        if self.kind == KIND_BOOLEAN:
            if self.choices:
                raise ContractError(f"{self.question_id}: boolean questions take no choices")
        else:
            if len(self.choices) < 2:
                raise ContractError(f"{self.question_id}: needs at least two choices")
            if len(self.choices) > MAX_CHOICES:
                raise ContractError(f"{self.question_id}: at most {MAX_CHOICES} choices")
            if len(set(self.choices)) != len(self.choices):
                raise ContractError(f"{self.question_id}: duplicate choices")


@dataclass(frozen=True)
class QuestionSet:
    """버전이 붙은 질문 묶음.

    질문을 코드 곳곳의 문자열로 두지 않는 이유는 §47.2에 있다 — 질문이 바뀌면 답의 의미가
    바뀌므로 **새 평가 대상**이 된다. 버전이 없으면 어제의 답과 오늘의 답을 같은 표에
    섞어 놓고 성적을 매기게 된다.
    """

    name: str
    version: int
    questions: tuple[Question, ...]

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ContractError("question set name is required")
        if int(self.version) < 1:
            raise ContractError("question set version must be positive")
        if not self.questions:
            raise ContractError(f"{self.name}: a question set needs at least one question")
        ids = [question.question_id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ContractError(f"{self.name}: duplicate question_id")

    @property
    def key(self) -> str:
        """원장에 남길 식별자. 버전이 붙어야 답을 섞지 않는다."""
        return f"{self.name}-v{self.version}"

    def get(self, question_id: str) -> Question:
        for question in self.questions:
            if question.question_id == question_id:
                return question
        raise ContractError(f"{self.name}: unknown question_id {question_id}")


def _probability(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise ContractError(f"{name} must be a probability in [0, 1]")
    return parsed


@dataclass(frozen=True)
class Answer:
    """질문 하나에 대한 답.

    `confidence`는 provider가 스스로 적은 확신이 아니라 **확률분포에서 유도한다**
    (`from_distribution`). 자칭 확신을 그대로 받으면 §18이 막으려던 문제가 그대로 들어온다.
    """

    question_id: str
    # boolean이면 "yes"/"no", choice면 고른 보기, score면 고른 등급.
    value: str
    # 보기별 확률. boolean은 {"yes": p, "no": 1-p}.
    distribution: Mapping[str, float]
    confidence: float

    def __post_init__(self) -> None:
        if not str(self.question_id).strip():
            raise ContractError("answer question_id is required")
        if not self.distribution:
            raise ContractError(f"{self.question_id}: answer needs a distribution")
        total = math.fsum(_probability(value, f"{self.question_id} probability")
                          for value in self.distribution.values())
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ContractError(f"{self.question_id}: distribution must sum to 1 (got {total:.6f})")
        if self.value not in self.distribution:
            raise ContractError(f"{self.question_id}: chosen value is not in the distribution")
        _probability(self.confidence, f"{self.question_id} confidence")

    @property
    def probability(self) -> float:
        """고른 답의 확률."""
        return float(self.distribution[self.value])

    @classmethod
    def from_distribution(
        cls, question_id: str, distribution: Mapping[str, float],
    ) -> "Answer":
        """확률분포에서 답과 신뢰도를 유도한다.

        신뢰도는 **최빈값과 차순위의 격차**다. 두 보기가 0.5/0.5면 답을 골라도 아는 게 없으므로
        신뢰도 0이고, 하나가 1.0이면 1이다. 최빈 확률을 그대로 신뢰도로 쓰면 보기가 많을 때
        (예: 5지선다에서 0.3) 낮은 확신이 과소평가된다.
        """
        if not distribution:
            raise ContractError(f"{question_id}: distribution is empty")
        ordered = sorted(distribution.items(), key=lambda item: (-float(item[1]), item[0]))
        best_value, best_probability = ordered[0]
        runner_up = float(ordered[1][1]) if len(ordered) > 1 else 0.0
        return cls(
            question_id=question_id,
            value=best_value,
            distribution=dict(distribution),
            confidence=max(0.0, min(1.0, float(best_probability) - runner_up)),
        )


@dataclass(frozen=True)
class JudgmentResult:
    """한 종목·한 질문묶음에 대한 provider 한 번의 응답.

    비용·지연을 답과 함께 든다 — provider 비교의 근거가 답의 품질만으로는 부족하기 때문이다
    (§48의 비교 항목).
    """

    provider: str
    model: str
    question_set_key: str
    answers: tuple[Answer, ...]
    latency_ms: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    # provider가 답하지 못한 질문. 조용히 빼면 답한 것만 세어 성적이 좋아 보인다.
    unanswered: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.provider).strip() or not str(self.model).strip():
            raise ContractError("judgment provider and model are required")
        ids = [answer.question_id for answer in self.answers]
        if len(ids) != len(set(ids)):
            raise ContractError("duplicate answer question_id")
        if not math.isfinite(float(self.latency_ms)) or float(self.latency_ms) < 0:
            raise ContractError("latency_ms must be finite and non-negative")

    def answer(self, question_id: str) -> Answer | None:
        for item in self.answers:
            if item.question_id == question_id:
                return item
        return None

    @property
    def is_complete(self) -> bool:
        return not self.unanswered

    @property
    def mean_confidence(self) -> float:
        """답한 질문들의 평균 신뢰도. 답이 없으면 0 — '모르는 것'을 확신으로 읽지 않는다."""
        if not self.answers:
            return 0.0
        return math.fsum(answer.confidence for answer in self.answers) / len(self.answers)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "question_set": self.question_set_key,
            "answers": {
                answer.question_id: {
                    "value": answer.value,
                    "probability": round(answer.probability, 6),
                    "confidence": round(answer.confidence, 6),
                }
                for answer in self.answers
            },
            "unanswered": list(self.unanswered),
            "mean_confidence": round(self.mean_confidence, 6),
            "latency_ms": round(float(self.latency_ms), 1),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            **dict(self.metadata),
        }


class JudgmentProvider:
    """구조화 판단 provider의 최소 계약.

    구현체는 `evaluate`만 제공하면 된다 — 결정론 규칙이든, 싼 LLM이든, Jev 같은
    System-One 모델이든 같은 질문에 같은 모양으로 답한다. 그래야 §48 비교가 성립한다.
    """

    name: str = "judgment"
    model: str = "unspecified"

    def evaluate(
        self,
        state: Any,
        questions: QuestionSet,
        *,
        features: Mapping[str, Any] | None = None,
    ) -> JudgmentResult:
        raise NotImplementedError


__all__ = [
    "Answer",
    "JudgmentProvider",
    "JudgmentResult",
    "KINDS",
    "KIND_BOOLEAN",
    "KIND_CHOICE",
    "KIND_SCORE",
    "MAX_CHOICES",
    "Question",
    "QuestionSet",
]
