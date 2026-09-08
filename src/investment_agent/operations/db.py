"""ETL 직후의 작은 운영 상태 전이.

수집은 각 data owner가 하고, 여기서는 그 결과를 알림 흐름에 넘기기 전에 필요한
한 단계만 처리한다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from investment_agent.notifications.outbox import Outbox

PRODUCER = "institutional"


def seed_institutional_baseline(filings: list[dict[str, Any]]) -> int:
    """이미 적재된 13F 공시를 알림 대상에서 미리 빼 둔다.

    outbox는 로컬 runtime SQLite가 소유한다. 전에는 여기서만 Postgres
    `notifications` 스키마에 직접 썼는데 그 스키마는 선언에 없다 — 13F backfill이
    마지막 단계에서 `PGRST106`으로 죽었고, 그 전까지 적재한 공시는 전부 "새 소식"이
    되어 다음 알림 실행에서 한꺼번에 나갈 상태였다.
    """
    if not filings:
        return 0
    current_period = max(str(row.get("period_end") or "") for row in filings)
    latest = [row for row in filings if str(row.get("period_end") or "") == current_period]
    rows: list[dict[str, Any]] = []
    for row in latest:
        accession_no = str(row.get("accession_no") or "")
        if not accession_no:
            continue
        rows.append({
            "producer": PRODUCER,
            "notification_key": accession_no,
            "kind": "filing",
            "entity_key": accession_no,
            "period_end": current_period,
        })
    # 분기 요약도 같은 기준으로 한 번만 막는다.
    rows.append({
        "producer": PRODUCER,
        "notification_key": f"quarterly:{current_period}:{len(latest)}",
        "kind": "backfill_baseline",
        "entity_key": f"period:{current_period}",
        "period_end": current_period,
    })
    Outbox().suppress(rows, now=datetime.now(timezone.utc))
    return len(rows)
