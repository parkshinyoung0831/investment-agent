"""경제 발표 알림의 reporting reader 경계. 보낼지 말지는 원장(엔진)이 판단한다."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from investment_agent.reporting.readers.financial import ReportingQueries

LOOKBACK_DAYS = 7


def load_released(database: Any, event_keys: list[str] | None = None, *,
                  now: datetime | None = None) -> list[dict]:
    """최근 first actual이 확인된 발표. 같은 발표를 여러 번 읽어도 원장이 한 번만 보낸다."""
    wanted = set(event_keys) if event_keys is not None else None
    if wanted == set():
        return []
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=LOOKBACK_DAYS)
    result = ReportingQueries(database).read(
        "macro_release_summary", start=cutoff, end=moment + timedelta(days=LOOKBACK_DAYS),
    )
    if result.status not in {"ok", "empty"}:
        raise RuntimeError("macro release reporting reader unavailable")
    return [
        row for row in result.rows
        if row.get("status") == "released"
        and row.get("first_actual_value") is not None
        and row.get("first_actual_at")
        and parse_time(row["first_actual_at"]) >= cutoff
        and (wanted is None or row.get("event_key") in wanted)
    ]


def parse_time(value: object) -> datetime:
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
