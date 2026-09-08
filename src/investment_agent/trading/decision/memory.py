"""평가가 끝난 과거 판단만 다음 판단의 사례 기억으로 제공한다."""
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


class CaseMemory:
    def __init__(self, repository: MemoryRepository, limit: int = 5):
        self.repository = repository
        self.limit = limit

    def for_ticker(self, ticker: str, *, as_of_at: datetime | None = None) -> list[dict]:
        """미평가 판단은 배제해 자기확증 메모리가 생기지 않게 한다."""
        return self.repository.evaluated_memories(ticker, self.limit, as_of_at)

    def render(self, ticker: str, *, as_of_at: datetime | None = None) -> str:
        rows = self.for_ticker(ticker, as_of_at=as_of_at)
        if not rows:
            return "평가가 완료된 과거 사례 없음"
        return canonical_json(rows)
