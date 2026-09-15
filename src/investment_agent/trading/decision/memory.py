"""평가가 끝난 과거 판단과, 결과를 아직 모르는 직전 판단을 구분해 다음 판단에 제공한다.

평가된 사례는 "무엇이 맞았나"를 가르치고, 직전 판단은 "어제 무엇을 근거로 무엇이라고 했나"를
알려 준다. 직전 판단이 없으면 어제 사라고 한 종목을 오늘 아무 설명 없이 팔라고 할 수 있다.
직전 판단은 결과를 담지 않는다 — 결과를 모르는 판단을 성적처럼 보여주면 자기확증이 된다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from investment_agent.platform.serialization import canonical_json


class MemoryRepository(Protocol):
    def evaluated_memories(
        self,
        ticker: str,
        limit: int = 5,
        as_of_at: datetime | None = None,
    ) -> list[dict]: ...


# 직전 판단에서 다음 판단에 넘기는 필드. 근거 원문·역할 토론은 넘기지 않는다(분량과 앵커링).
# evidence_ids도 넘기지 않는다 — 그날 번들의 ID라 오늘 인용하면 계약 위반으로 종목 전체가 실패한다.
_PREVIOUS_FIELDS = ("signal", "expected_excess_return", "probability_up", "confidence")
_PREVIOUS_REASONS = 3


class CaseMemory:
    def __init__(self, repository: MemoryRepository, limit: int = 5):
        self.repository = repository
        self.limit = limit

    def for_ticker(self, ticker: str, *, as_of_at: datetime | None = None) -> list[dict]:
        """미평가 판단은 배제해 자기확증 메모리가 생기지 않게 한다."""
        return self.repository.evaluated_memories(ticker, self.limit, as_of_at)

    def previous_view(self, ticker: str, *, as_of_at: datetime | None) -> dict | None:
        if as_of_at is None or not hasattr(self.repository, "previous_decision"):
            return None
        row = self.repository.previous_decision(ticker, as_of_at=as_of_at)
        decision = (row or {}).get("final_decision")
        if not isinstance(decision, dict):
            return None
        return {
            "case_key": row["case_key"],
            "as_of_at": row["as_of_at"],
            **{key: decision.get(key) for key in _PREVIOUS_FIELDS},
            "reasoning": list(decision.get("reasoning") or ())[:_PREVIOUS_REASONS],
            "outcome": "아직 평가되지 않음 — 이 판단이 맞았는지 모른다",
        }

    def render(self, ticker: str, *, as_of_at: datetime | None = None) -> str:
        rows = self.for_ticker(ticker, as_of_at=as_of_at)
        previous = self.previous_view(ticker, as_of_at=as_of_at)
        if not rows and previous is None:
            return "평가가 완료된 과거 사례 없음"
        payload: dict = {"evaluated_cases": rows or "평가가 완료된 과거 사례 없음"}
        if previous is not None:
            payload["previous_decision"] = previous
            payload["continuity_rule"] = (
                "직전 판단과 행동 방향이 달라지면 reasoning 첫 줄에 무엇이 새로 바뀌었는지 오늘 근거 ID와 함께 적는다. "
                "새 근거가 없으면 방향을 뒤집지 않는다. 직전 판단은 결과가 확인되지 않았으므로 정답으로 취급하지 않는다."
            )
        return canonical_json(payload)
