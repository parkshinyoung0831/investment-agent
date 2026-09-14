"""성과 보고서와 명시적인 원가·현금흐름 증거의 로컬 저장 경계."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from investment_agent.platform.db.sqlite import runtime_connection, default_runtime_database_path
from investment_agent.platform.serialization import parse_datetime, stable_id


class PerformanceRepository:
    def __init__(self, path: Path | str | None = None):
        self.path = path

    def save_report(self, payload: dict) -> bool:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        with runtime_connection(self.path) as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO performance_reports VALUES(?,?,?,?,?,?,?,?)",
                (payload["report_id"], payload["broker_account_hash"], payload["execution_mode"],
                 payload["report_kind"], payload["occurrence"], payload["as_of_at"], encoded,
                 datetime.now(timezone.utc).isoformat()))
        return cursor.rowcount == 1

    def save_event(self, event: dict) -> bool:
        """원천 참조가 있는 불변 보정 사건만 수용한다. 동일 ID의 변경은 거부한다."""
        if not event.get("event_id") or not event.get("source_ref") or not event.get("broker_account_hash"):
            raise ValueError("event requires identity, account and source evidence")
        if event.get("kind") not in ("deposit", "withdrawal", "split", "dividend", "opening", "coverage"):
            raise ValueError("unsupported performance event")
        event = dict(event, occurred_at=parse_datetime(event["occurred_at"]).isoformat())
        encoded = json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False)
        with runtime_connection(self.path) as connection:
            old = connection.execute("SELECT payload_json FROM performance_events WHERE event_id=?", (event["event_id"],)).fetchone()
            if old:
                if old[0] != encoded:
                    raise ValueError("conflicting performance event")
                return False
            connection.execute("INSERT INTO performance_events VALUES(?,?,?,?,?)", (
                event["event_id"], event["broker_account_hash"], event["execution_mode"], event["occurred_at"], encoded))
        return True

    def events(self) -> list[dict]:
        with runtime_connection(self.path) as connection:
            rows = connection.execute("SELECT payload_json FROM performance_events ORDER BY occurred_at,event_id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def reports(self) -> list[dict]:
        if not Path(self.path or default_runtime_database_path()).exists():
            return []
        with runtime_connection(self.path, read_only=True) as connection:
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='performance_reports'").fetchone():
                return []
            rows = connection.execute("SELECT payload_json FROM performance_reports ORDER BY as_of_at,created_at,report_id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def latest_performance(self) -> dict | None:
        rows = [row for row in self.reports() if row["report_kind"] == "daily"]
        return rows[-1] if rows else None


def report_identity(payload):
    """계산 시각 대신 내용으로 revision을 만든다."""
    return stable_id("performance", payload)
