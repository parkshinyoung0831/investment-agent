"""Research 로컬 전략 결과를 알림용 모양으로 읽는 저장소 경계."""
from __future__ import annotations

from investment_agent.research.storage.repository import ResearchStore
from investment_agent.notifications.outbox import Outbox


def _store() -> ResearchStore:
    return ResearchStore()


def load_pending() -> list[dict]:
    """아직 발송 표시가 없는 전략 배분을 오래된 순서로 읽는다."""
    completed = Outbox().sent_keys("strategy", kind="strategy")
    return [
        row for row in _store().allocations()
        if f"allocation:{row['strategy_id']}:{row['apply_date']}" not in completed
    ]


def load_prev_alloc(strategy_id: str, apply_date: str) -> dict | None:
    return _store().previous_allocation(strategy_id, apply_date)


def mark_sent(
    allocation_id: int | str,
    *,
    strategy_id: str | None = None,
    apply_date: str | None = None,
) -> None:
    """호환용 no-op. 완료 상태는 runtime outbox만 소유한다."""
    del allocation_id
    if strategy_id is None or apply_date is None:
        raise ValueError("strategy_id and apply_date are required for local allocations")
    # 호출자가 넘긴 identity를 검증해 잘못된 카드가 조용히 넘어가지 않게 한다.
    if not strategy_id.strip() or not apply_date.strip():
        raise ValueError("strategy_id and apply_date must not be empty")
