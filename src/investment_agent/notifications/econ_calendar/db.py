"""경제 발표 알림의 reporting reader와 outbox 경계."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from investment_agent.notifications.outbox import Outbox
from investment_agent.reporting.readers.financial import ReportingQueries

PRODUCER = "macro_releases"
KIND = "macro_release"
_LOOKBACK_DAYS = 7
_outbox: Outbox | None = None
_reporting: ReportingQueries | None = None


def configure(outbox: Outbox, database: object | None = None) -> None:
    global _outbox, _reporting
    _outbox = outbox
    if database is not None:
        _reporting = ReportingQueries(database)  # type: ignore[arg-type]


def _get_outbox() -> Outbox:
    if _outbox is None:
        raise RuntimeError("econ calendar notification store is not configured")
    return _outbox


def _get_reporting() -> ReportingQueries:
    if _reporting is None:
        raise RuntimeError("econ calendar reporting reader is not configured")
    return _reporting


def notification_key(key: str) -> str:
    from investment_agent.reporting.services.economic_releases import parse_event_key

    if parse_event_key(key) is None:
        raise ValueError("invalid economic release event key")
    return f"first_actual:{key}"


def load_pending(event_keys: list[str] | None = None) -> list[dict]:
    wanted = set(event_keys) if event_keys is not None else None
    if wanted == set():
        return []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_LOOKBACK_DAYS)
    result = _get_reporting().read(
        "macro_release_summary",
        start=cutoff,
        end=now + timedelta(days=_LOOKBACK_DAYS),
    )
    if result.status not in {"ok", "empty"}:
        raise RuntimeError("macro release reporting reader unavailable")
    rows = result.rows
    rows = [
        row for row in rows
        if row.get("status") == "released"
        and row.get("first_actual_value") is not None
        and row.get("first_actual_at")
        and datetime.fromisoformat(str(row["first_actual_at"]).replace("Z", "+00:00")) >= cutoff
        and (wanted is None or row.get("event_key") in wanted)
    ]
    pending = _get_outbox().filter_pending(
        PRODUCER,
        [notification_key(str(row["event_key"])) for row in rows],
        kind=KIND,
    )
    pending_set = set(pending)
    return [row for row in rows if notification_key(str(row["event_key"])) in pending_set]
