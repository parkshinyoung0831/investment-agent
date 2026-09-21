"""알림 원장의 Supabase 경계. 이 패키지에서 쿼리를 만드는 곳은 여기뿐이다.

판단(예약·전송 시작·결과 기록)은 SQL 함수가 서버 시각으로 내린다. 여기서는 부르고
응답 모양만 검증한다. Supabase에 닿지 못하면 예외가 그대로 올라간다 — 호출자는
그때 보내지 않는다(fail-closed).
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from investment_agent.notifications.ledger import (
    ACTIONS,
    STUCK_SENDING_SECONDS,
    KnownNotice,
    NoticeState,
    Reservation,
)
from investment_agent.platform.serialization import json_value

SCHEMA = "notifications"
T_TOPICS = "topics"
T_NOTICES = "notices"
T_THREADS = "threads"
RPC_RESERVE = "reserve"
RPC_BEGIN_SEND = "begin_send"
RPC_FINISH = "finish"
RPC_REPLAY = "replay"


def _keys(keys: Sequence[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"subject": subject, "occurrence": occurrence} for subject, occurrence in keys]


def _count(response: Any) -> int:
    data = response.data
    if isinstance(data, list):
        data = data[0] if data else 0
    if isinstance(data, dict):
        data = next(iter(data.values()), 0)
    if isinstance(data, bool) or not isinstance(data, int):
        raise RuntimeError("notification ledger returned an unexpected count")
    return data


class PostgresNotificationLedger:
    """`NotificationLedger` 계약의 Supabase 구현."""

    def __init__(self, database: Any) -> None:
        self._db = database

    def ensure_baseline(self, topic: str, baseline_at: datetime) -> bool:
        return bool(self._db.insert_ignore_duplicate(
            schema=SCHEMA, table=T_TOPICS,
            row={"topic": topic, "baseline_at": baseline_at.isoformat()},
        ))

    def reserve(self, topic: str, items: Sequence[dict[str, Any]], *, owner: str,
                lease_seconds: int, revisable: bool) -> list[Reservation]:
        response = self._db.rpc(SCHEMA, RPC_RESERVE, {
            "p_topic": topic,
            "p_items": json_value(list(items)),
            "p_owner": owner,
            "p_lease_seconds": lease_seconds,
            "p_revisable": revisable,
        }).execute()
        out = []
        for row in response.data or []:
            action = str(row.get("action") or "")
            if action not in ACTIONS:
                raise RuntimeError("notification ledger returned an unknown action")
            out.append(Reservation(
                subject=str(row["subject"]),
                occurrence=str(row["occurrence"]),
                action=action,
                location_id=row.get("location_id"),
                message_id=row.get("message_id"),
                attempts=int(row.get("attempts") or 0),
            ))
        return out

    def begin_send(self, topic: str, keys: Sequence[tuple[str, str]], *, owner: str) -> int:
        return _count(self._db.rpc(SCHEMA, RPC_BEGIN_SEND, {
            "p_topic": topic, "p_keys": _keys(keys), "p_owner": owner,
        }).execute())

    def finish(self, topic: str, keys: Sequence[tuple[str, str]], *, owner: str, action: str,
               outcome: str, location_id: str | None, message_id: str | None,
               failure_code: str | None, retry_seconds: int | None) -> int:
        return _count(self._db.rpc(SCHEMA, RPC_FINISH, {
            "p_topic": topic, "p_keys": _keys(keys), "p_owner": owner,
            "p_action": action, "p_outcome": outcome,
            "p_location_id": location_id, "p_message_id": message_id,
            "p_failure_code": failure_code, "p_retry_seconds": retry_seconds,
        }).execute())

    def replay(self, topic: str, subject: str, occurrence: str) -> int:
        return _count(self._db.rpc(SCHEMA, RPC_REPLAY, {
            "p_topic": topic, "p_subject": subject, "p_occurrence": occurrence,
        }).execute())

    def stuck_sending(self, *, older_than_seconds: int = STUCK_SENDING_SECONDS) -> list[tuple[str, str, str]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
        rows = self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_NOTICES)
            .select("topic,subject,occurrence")
            .eq("status", "sending")
            .lt("updated_at", cutoff),
            order_by="topic,subject,occurrence",
        )
        return [(str(row["topic"]), str(row["subject"]), str(row["occurrence"])) for row in rows]

    def last_known(self, topic: str, subject: str) -> KnownNotice | None:
        rows = (
            self._db.table(SCHEMA, T_NOTICES)
            .select("occurrence,status,revision,sent_revision")
            .eq("topic", topic)
            .eq("subject", subject)
            .in_("status", ["sent", "suppressed"])
            .order("first_seen_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not rows:
            return None
        row = rows[0]
        revision = row["sent_revision"] if row["status"] == "sent" else row["revision"]
        return KnownNotice(str(row["occurrence"]), str(revision))

    def states(self, topic: str, keys: Sequence[tuple[str, str]]) -> dict[tuple[str, str], NoticeState]:
        wanted = set(keys)
        subjects = sorted({subject for subject, _ in wanted})
        if not subjects:
            return {}
        rows = self._db.select_in_chunks(
            schema=SCHEMA, table=T_NOTICES,
            columns="subject,occurrence,status,revision,sent_revision",
            filter_column="subject", values=subjects,
            configure=lambda query: query.eq("topic", topic),
            order_by="subject,occurrence",
        )
        return {
            (str(row["subject"]), str(row["occurrence"])): NoticeState(
                str(row["status"]), str(row["revision"]), row.get("sent_revision"),
            )
            for row in rows
            if (str(row["subject"]), str(row["occurrence"])) in wanted
        }

    def thread(self, channel_id: str, thread_key: str) -> str | None:
        rows = (
            self._db.table(SCHEMA, T_THREADS)
            .select("thread_id")
            .eq("channel_id", channel_id)
            .eq("thread_key", thread_key)
            .limit(1)
            .execute()
            .data
            or []
        )
        return str(rows[0]["thread_id"]) if rows else None

    def remember_thread(self, channel_id: str, thread_key: str, thread_id: str) -> None:
        # 스레드가 지워져 새로 만든 경우 같은 키의 목적지를 바꿔 적는다.
        self._db.upsert(
            schema=SCHEMA, table=T_THREADS,
            rows=[{"channel_id": channel_id, "thread_key": thread_key, "thread_id": thread_id}],
            on_conflict="channel_id,thread_key",
        )


__all__ = [
    "PostgresNotificationLedger", "RPC_BEGIN_SEND", "RPC_FINISH", "RPC_REPLAY", "RPC_RESERVE",
    "SCHEMA", "T_NOTICES", "T_THREADS", "T_TOPICS",
]
