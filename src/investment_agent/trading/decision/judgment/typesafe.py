"""TypeSafe(Jev) System-One provider 어댑터.

## 이 파일이 존재한다고 Jev가 채택된 것은 아니다

`INVESTMENT_DECISION_ENGINE_DESIGN.md` §49.2의 판정은 여전히 `RESEARCH ONLY`다. 이것은
**shadow 비교를 돌릴 수 있게 하는 레일**이다 — 레일이 없으면 비교 데이터가 영원히 안 쌓이고,
데이터가 없으면 판정을 못 하는 순환에 빠진다. 결과는 기록만 하고 Alpha·비중·주문에 닿지
않는다(§51, `SYSTEM_UPGRADE_MASTER.md` §4.2).

## 벤더 어휘를 계약 밖으로 내보내지 않는다

Jev의 primitive(Noul/Choice/Score)는 여기서만 안다. 위층은 `Question.kind`
(boolean/choice/score)만 본다 — 그래야 provider를 바꿔도 질문과 채점이 그대로다(§44).

## 알려진 제약 (공식 문서, 2026-09-22 조사)

- 문자열을 생성하지 않는다. 논지 서술·key_risks는 이 provider로 만들 수 없다.
- 비영어(CJK 포함) 정확도가 낮다고 공식 명시 — 이 저장소 질문은 한국어다.
  그래서 비교 시 **Champion과 다른 프롬프트**가 되지 않게, 질문 번역 여부를 artifact에 남긴다.
- Choice 보기 상한 255. 우리 계약은 32로 더 좁다(`contracts.MAX_CHOICES`).
"""
from __future__ import annotations

import os
import time
from typing import Any, Mapping

import httpx

from investment_agent.platform.env import env_float
from investment_agent.platform.serialization import ContractError, canonical_json
from investment_agent.trading.decision.judgment.contracts import (
    KIND_BOOLEAN,
    KIND_CHOICE,
    KIND_SCORE,
    Answer,
    JudgmentProvider,
    JudgmentResult,
    QuestionSet,
)

API_KEY_ENV = "AI_INVESTOR_TYPESAFE_API_KEY"
BASE_URL_ENV = "AI_INVESTOR_TYPESAFE_BASE_URL"
MODEL_ENV = "AI_INVESTOR_TYPESAFE_MODEL"

DEFAULT_BASE_URL = "https://api.typesafe.ai/v1"
# `jev-latest`를 쓰지 않는다. 버전이 떠 있으면 어제의 답과 오늘의 답이 다른 모델에서 나오고,
# 그러면 채점이 무의미해진다(§52 "Provider model version floating" 금지).
DEFAULT_MODEL = "jev-1.13.0"

# 우리 kind → Jev primitive. 이 표가 이 파일 밖으로 나가지 않는다.
_PRIMITIVE_BY_KIND = {
    KIND_BOOLEAN: "noul",
    KIND_CHOICE: "choice",
    KIND_SCORE: "score",
}


class TypeSafeConfigError(RuntimeError):
    """키·설정이 없어 호출할 수 없다. 조용히 건너뛰지 않고 호출부가 알게 한다."""


class TypeSafeJudge(JudgmentProvider):
    """Jev에 같은 질문을 던지고 같은 모양의 답을 받는다."""

    name = "typesafe"

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        timeout_sec: float | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get(API_KEY_ENV, "").strip()
        self.base_url = (base_url or os.environ.get(BASE_URL_ENV, "") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get(MODEL_ENV, "") or DEFAULT_MODEL
        self.timeout_sec = timeout_sec if timeout_sec is not None else env_float(
            "AI_INVESTOR_TYPESAFE_TIMEOUT_SEC", 30.0
        )

    @classmethod
    def is_configured(cls) -> bool:
        """키가 있는가. shadow 실행을 붙이기 전에 호출부가 먼저 묻는다."""
        return bool(os.environ.get(API_KEY_ENV, "").strip())

    def _payload(self, state: Any, questions: QuestionSet) -> dict[str, Any]:
        """Jev 요청 본문. 질문은 한 번에 보낸다 — 서로 독립으로 병렬 평가된다."""
        items: list[dict[str, Any]] = []
        for question in questions.questions:
            item: dict[str, Any] = {
                "id": question.question_id,
                "type": _PRIMITIVE_BY_KIND[question.kind],
                "question": question.prompt,
            }
            if question.choices:
                item["options"] = list(question.choices)
            items.append(item)
        return {
            "model": self.model,
            "state": state if isinstance(state, str) else canonical_json(state),
            "questions": items,
        }

    @staticmethod
    def _distribution(question, raw: Mapping[str, Any]) -> dict[str, float]:
        """provider 응답을 우리 확률분포로 옮긴다. 모양이 어긋나면 조용히 채우지 않는다."""
        if question.kind == KIND_BOOLEAN:
            probability = raw.get("probability")
            if probability is None:
                raise ContractError(f"{question.question_id}: boolean answer has no probability")
            value = max(0.0, min(1.0, float(probability)))
            return {"yes": value, "no": 1.0 - value}
        distribution = raw.get("distribution")
        if not isinstance(distribution, Mapping) or not distribution:
            raise ContractError(f"{question.question_id}: answer has no distribution")
        unknown = sorted(set(map(str, distribution)) - set(question.choices))
        if unknown:
            raise ContractError(
                f"{question.question_id}: answer used options outside the question: {unknown}"
            )
        return {str(key): float(value) for key, value in distribution.items()}

    def evaluate(
        self,
        state: Any,
        questions: QuestionSet,
        *,
        features: Mapping[str, Any] | None = None,
    ) -> JudgmentResult:
        if not self.api_key:
            raise TypeSafeConfigError(
                f"{API_KEY_ENV} is not set; refusing to send an unauthenticated request"
            )
        started = time.monotonic()
        with httpx.Client(timeout=self.timeout_sec) as client:
            response = client.post(
                f"{self.base_url}/evaluate",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=self._payload(state, questions),
            )
            response.raise_for_status()
            body = response.json()
        latency_ms = (time.monotonic() - started) * 1000.0

        raw_answers = body.get("answers") if isinstance(body, Mapping) else None
        if not isinstance(raw_answers, Mapping):
            raise ContractError("TypeSafe response has no answers object")
        answers: list[Answer] = []
        unanswered: list[str] = []
        for question in questions.questions:
            raw = raw_answers.get(question.question_id)
            if not isinstance(raw, Mapping):
                unanswered.append(question.question_id)
                continue
            answers.append(
                Answer.from_distribution(
                    question.question_id, self._distribution(question, raw)
                )
            )
        usage = body.get("usage") if isinstance(body, Mapping) else None
        input_tokens = None
        if isinstance(usage, Mapping):
            raw_input = usage.get("input_tokens")
            input_tokens = int(raw_input) if isinstance(raw_input, int) else None
        return JudgmentResult(
            provider=self.name,
            model=self.model,
            question_set_key=questions.key,
            answers=tuple(answers),
            unanswered=tuple(unanswered),
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            # Jev는 출력 토큰을 과금하지 않는다. 0이 아니라 None으로 둔다 —
            # "안 썼다"와 "해당 없음"을 같은 값으로 적지 않는다.
            output_tokens=None,
            metadata={"question_language": "ko"},
        )


__all__ = [
    "API_KEY_ENV",
    "BASE_URL_ENV",
    "DEFAULT_MODEL",
    "MODEL_ENV",
    "TypeSafeConfigError",
    "TypeSafeJudge",
]
