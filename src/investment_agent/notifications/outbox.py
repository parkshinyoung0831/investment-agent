"""로컬 SQLite 알림 원장.

알림 중복 방지와 전송 결과는 실행 컴퓨터에서만 의미가 있는 상태다. Supabase가
canonical 금융 사실을 보관하는 동안 이 원장은 ``runtime.sqlite3``에 남긴다.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.platform.serialization import canonical_json, parse_datetime
from investment_agent.reporting.models import sanitize_message

T_OUTBOX = "notification_outbox"
T_DELIVERIES = "notification_deliveries"


@dataclass(frozen=True)
class Attempt:
    row: dict[str, Any]


def _decode(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = ("producer", "notification_key", "kind", "entity_key", "period_end", "payload_json", "status", "attempt_count", "claimed_at", "resolved_at")
    value = dict(zip(keys, row))
    value["payload"] = json.loads(value.pop("payload_json"))
    return value


class Outbox:
    """SQLite 조건부 갱신으로 발송 권한을 한 번만 선점한다."""

    def __init__(self, _database: Any | None = None) -> None:
        # 호출자 호환성을 위해 받되 외부 DB는 사용하지 않는다.
        del _database

    def enqueue(self, *, producer: str, notification_key: str, kind: str, target: str, message: dict[str, Any], now: datetime, entity_key: str | None = None, period_end: date | str | None = None, attachment_path: str | None = None,
                thread_name: str | None = None, thread_tags: tuple[str, ...] = ()) -> bool:
        if not all(isinstance(value, str) and value.strip() for value in (producer, notification_key, kind, target)):
            raise ValueError("notification identity must not be empty")
        if not target.isascii() or not target.isdigit() or not isinstance(message, dict):
            raise ValueError("notification target or message is invalid")
        payload = {"channel": "discord", "target": target, "message": deepcopy(message)}
        if attachment_path:
            payload["attachment_path"] = attachment_path
        # 포럼 목적지는 전송 시점이 아니라 등록 시점에 정해진다. 나중에 다시 계산하면
        # 그 사이 선언이 바뀐 경우 같은 알림이 다른 채널로 간다.
        if thread_name:
            payload["thread_name"] = thread_name
            if thread_tags:
                payload["thread_tags"] = list(thread_tags)
        now_iso = parse_datetime(now).isoformat()
        period = period_end.isoformat() if isinstance(period_end, date) else period_end
        with runtime_connection() as connection:
            try:
                connection.execute(f"INSERT INTO {T_OUTBOX} (producer,notification_key,kind,entity_key,period_end,payload_json,status,attempt_count,claimed_at) VALUES (?,?,?,?,?,?, 'pending',0,?)", (producer, notification_key, kind, entity_key, period, canonical_json(payload), now_iso))
                return True
            except Exception as exc:
                existing = connection.execute(f"SELECT producer,notification_key,kind,entity_key,period_end,payload_json,status,attempt_count,claimed_at,resolved_at FROM {T_OUTBOX} WHERE producer=? AND notification_key=?", (producer, notification_key)).fetchone()
                if existing is None:
                    raise exc
                row = _decode(existing)
                if row["kind"] != kind or row.get("entity_key") != entity_key or row.get("period_end") != period or canonical_json(row["payload"]) != canonical_json(payload):
                    raise ValueError("notification key conflicts with its stored snapshot") from exc
                return False

    def suppress(self, rows: list[dict[str, Any]], *, now: datetime) -> int:
        """이미 아는 알림을 보내지 않은 채 해소 상태로 등록한다.

        backfill 직후에 쓴다 — 과거치를 처음 적재하면 그 전부가 "새 소식"이 되어
        한꺼번에 나간다. 이미 있는 키는 건드리지 않는다(그 알림은 이미 자기
        상태를 갖고 있다).
        """
        now_iso = parse_datetime(now).isoformat()
        written = 0
        with runtime_connection() as connection:
            for row in rows:
                producer = str(row.get("producer") or "")
                key = str(row.get("notification_key") or "")
                kind = str(row.get("kind") or "")
                if not (producer and key and kind):
                    raise ValueError("suppressed notification identity must not be empty")
                period_end = row.get("period_end")
                period = period_end.isoformat() if isinstance(period_end, date) else period_end
                cursor = connection.execute(
                    f"INSERT OR IGNORE INTO {T_OUTBOX} "
                    "(producer,notification_key,kind,entity_key,period_end,payload_json,"
                    "status,attempt_count,claimed_at,resolved_at) "
                    "VALUES (?,?,?,?,?,?, 'abandoned',0,?,?)",
                    (producer, key, kind, row.get("entity_key"), period,
                     canonical_json({"suppressed": True}), now_iso, now_iso),
                )
                written += int(cursor.rowcount or 0)
        return written

    def get(self, producer: str, notification_key: str) -> dict[str, Any] | None:
        with runtime_connection(read_only=True) as connection:
            row = connection.execute(f"SELECT producer,notification_key,kind,entity_key,period_end,payload_json,status,attempt_count,claimed_at,resolved_at FROM {T_OUTBOX} WHERE producer=? AND notification_key=?", (producer, notification_key)).fetchone()
        return _decode(row) if row else None

    def sent_keys(self, producer: str, *, kind: str | None = None) -> set[str]:
        with runtime_connection(read_only=True) as connection:
            statement = f"SELECT notification_key FROM {T_OUTBOX} WHERE producer=?" + (" AND kind=?" if kind else "")
            rows = connection.execute(statement, (producer, kind) if kind else (producer,)).fetchall()
        return {str(row[0]) for row in rows}

    def filter_pending(self, producer: str, keys: list[str], *, kind: str | None = None) -> list[str]:
        sent = self.sent_keys(producer, kind=kind)
        return [key for key in keys if key not in sent]

    def ready(self, *, now: datetime) -> list[dict[str, Any]]:
        moment = parse_datetime(now)
        with runtime_connection(read_only=True) as connection:
            rows = connection.execute(f"SELECT producer,notification_key,kind,entity_key,period_end,payload_json,status,attempt_count,claimed_at,resolved_at FROM {T_OUTBOX} WHERE (status='pending' AND attempt_count=0) OR status='failed' ORDER BY claimed_at,producer,notification_key").fetchall()
        return [row for row in map(_decode, rows) if not row["payload"].get("retry_not_before") or parse_datetime(row["payload"]["retry_not_before"]) <= moment]

    def claim(self, row: dict[str, Any], *, now: datetime, max_attempts: int) -> Attempt | None:
        count = int(row["attempt_count"])
        if row["status"] not in {"pending", "failed"} or count >= max_attempts or (row["status"] == "pending" and count):
            return None
        moment = parse_datetime(now)
        if row["payload"].get("retry_not_before") and parse_datetime(row["payload"]["retry_not_before"]) > moment:
            return None
        with runtime_connection() as connection:
            result = connection.execute(f"UPDATE {T_OUTBOX} SET status='pending',attempt_count=?,claimed_at=?,resolved_at=NULL WHERE producer=? AND notification_key=? AND status=? AND attempt_count=?", (count + 1, moment.isoformat(), row["producer"], row["notification_key"], row["status"], count))
        if result.rowcount != 1:
            return None
        return Attempt({**deepcopy(row), "status": "pending", "attempt_count": count + 1, "claimed_at": moment.isoformat(), "resolved_at": None})

    def record(self, attempt: Attempt, *, status: str, now: datetime, failure_reason: str | None = None, retry_after: float = 60) -> None:
        if status not in {"sent", "failed", "abandoned", "unknown"}:
            raise ValueError("invalid notification outcome")
        row, moment = attempt.row, parse_datetime(now)
        payload = deepcopy(row["payload"])
        if status == "unknown":
            return
        payload.pop("retry_not_before", None)
        if status == "failed":
            payload["retry_not_before"] = (moment + timedelta(seconds=retry_after)).isoformat()
        with runtime_connection() as connection:
            connection.execute(f"INSERT INTO {T_DELIVERIES} (producer,notification_key,status,failure_reason,attempted_at) VALUES (?,?,?,?,?)", (row["producer"], row["notification_key"], "sent" if status == "sent" else "failed", sanitize_message(failure_reason) if failure_reason else None, moment.isoformat()))
            result = connection.execute(f"UPDATE {T_OUTBOX} SET status=?,resolved_at=?,payload_json=? WHERE producer=? AND notification_key=? AND status='pending' AND attempt_count=? AND claimed_at=?", (status, moment.isoformat(), canonical_json(payload), row["producer"], row["notification_key"], row["attempt_count"], row["claimed_at"]))
            if result.rowcount != 1:
                raise RuntimeError("notification outcome was not finalized")


__all__ = ["Attempt", "Outbox", "T_DELIVERIES", "T_OUTBOX"]
