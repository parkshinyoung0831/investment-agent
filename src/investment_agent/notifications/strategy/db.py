"""Research 로컬 전략 결과를 알림용 모양으로 읽는 저장소 경계. 보낼지 말지는 알림 원장이 판단한다."""
from __future__ import annotations

from datetime import date, timedelta

from investment_agent.research.storage.repository import ResearchStore

#: 최신 적용월에서 이만큼 이전까지만 알림 후보로 본다. 오래된 배분은 원장 baseline이 막지만
#: 전략 이력 전체를 매달 원장에 묻지 않는다.
RECENT_DAYS = 100


def _store() -> ResearchStore:
    return ResearchStore()


def load_recent_allocations() -> list[dict]:
    """최근 적용월의 전략 배분을 오래된 순서로 읽는다."""
    rows = _store().allocations()
    if not rows:
        return []
    latest = max(date.fromisoformat(str(row["apply_date"])[:10]) for row in rows)
    since = (latest - timedelta(days=RECENT_DAYS)).isoformat()
    return sorted(
        (row for row in rows if str(row["apply_date"])[:10] >= since),
        key=lambda row: (str(row["apply_date"]), str(row["strategy_id"])),
    )


def load_prev_alloc(strategy_id: str, apply_date: str) -> dict | None:
    return _store().previous_allocation(strategy_id, apply_date)
