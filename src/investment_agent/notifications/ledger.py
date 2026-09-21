"""알림 원장의 계약. 저장소는 Supabase `notifications` 스키마 하나다(`notifications/db.py`).

원장이 답하는 질문은 셋이다.
1. 이 알림을 지금 이 실행이 보내도 되는가 — `reserve`
2. 보내기 직전에 아직 이 실행의 몫인가 — `begin_send`
3. 보낸 결과는 무엇이었나 — `finish`

판단은 서버 시각으로 한 곳에서 내린다(`db/postgres/v1/60_notifications.sql`). 여기의
`MemoryLedger`는 그 함수들과 같은 규칙을 따르는 테스트용 구현이다 — 규칙을 바꾸면
SQL과 이 파일을 함께 고치고 `scripts/verify_notification_ledger.py`로 실DB와 맞춘다.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

ACTIONS = frozenset({"create", "edit", "suppressed"})
OUTCOMES = frozenset({"sent", "failed", "abandoned", "unknown"})
MIN_LEASE_SECONDS, MAX_LEASE_SECONDS = 30, 3600
# 전송 호출 하나는 몇 초면 끝난다. 이보다 오래 `sending`이면 전송 도중 프로세스가 죽은 것이라, 보냈는지 알 수 없고
# 자동으로 다시 보내지도 않는다(중복 방지). 사람이 확인하도록 드러내는 기준이다.
STUCK_SENDING_SECONDS = 1800


@dataclass(frozen=True)
class Reservation:
    """이 실행이 맡은 알림 하나. action이 무엇을 할지 말한다."""

    subject: str
    occurrence: str
    action: str
    location_id: str | None = None
    message_id: str | None = None
    attempts: int = 0

    @property
    def key(self) -> tuple[str, str]:
        return self.subject, self.occurrence


@dataclass(frozen=True)
class NoticeState:
    """원장에 적힌 알림 하나의 현재 상태(읽기 전용 판단용)."""

    status: str
    revision: str
    sent_revision: str | None = None


@dataclass(frozen=True)
class KnownNotice:
    """사람이 이미 아는 가장 최근 알림 — 보냈거나, 원장 도입 전에 보낸 것으로 억제한 것."""

    occurrence: str
    revision: str


class NotificationLedger(Protocol):
    def ensure_baseline(self, topic: str, baseline_at: datetime) -> bool: ...

    def reserve(self, topic: str, items: Sequence[dict[str, Any]], *, owner: str,
                lease_seconds: int, revisable: bool) -> list[Reservation]: ...

    def begin_send(self, topic: str, keys: Sequence[tuple[str, str]], *, owner: str) -> int: ...

    def finish(self, topic: str, keys: Sequence[tuple[str, str]], *, owner: str, action: str,
               outcome: str, location_id: str | None, message_id: str | None,
               failure_code: str | None, retry_seconds: int | None) -> int: ...

    def replay(self, topic: str, subject: str, occurrence: str) -> int: ...

    def stuck_sending(self, *, older_than_seconds: int = STUCK_SENDING_SECONDS) -> list[tuple[str, str, str]]:
        """`sending`에서 멈춘 알림의 (topic, subject, occurrence). 자동 재전송 대상이 아니라 확인 대상이다."""
        ...

    def last_known(self, topic: str, subject: str) -> KnownNotice | None: ...

    def states(self, topic: str, keys: Sequence[tuple[str, str]]) -> dict[tuple[str, str], NoticeState]: ...

    def thread(self, channel_id: str, thread_key: str) -> str | None: ...

    def remember_thread(self, channel_id: str, thread_key: str, thread_id: str) -> None: ...


@dataclass
class _Row:
    topic: str
    subject: str
    occurrence: str
    revision: str
    fact_at: datetime
    status: str
    first_seen_at: datetime
    updated_at: datetime
    attempts: int = 0
    owner: str | None = None
    lease_until: datetime | None = None
    retry_at: datetime | None = None
    location_id: str | None = None
    message_id: str | None = None
    sent_revision: str | None = None
    failure_code: str | None = None


class MemoryLedger:
    """`60_notifications.sql`의 함수와 같은 규칙을 메모리에서 따른다(테스트 전용)."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.baselines: dict[str, datetime] = {}
        self.rows: dict[tuple[str, str, str], _Row] = {}
        self.deliveries: list[dict[str, Any]] = []
        self.threads: dict[tuple[str, str], str] = {}

    def ensure_baseline(self, topic: str, baseline_at: datetime) -> bool:
        if topic in self.baselines:
            return False
        self.baselines[topic] = baseline_at
        return True

    def reserve(self, topic: str, items: Sequence[dict[str, Any]], *, owner: str,
                lease_seconds: int, revisable: bool) -> list[Reservation]:
        if not owner or not owner.strip():
            raise ValueError("reserve requires an owner")
        if not MIN_LEASE_SECONDS <= lease_seconds <= MAX_LEASE_SECONDS:
            raise ValueError("reserve lease must be between 30 and 3600 seconds")
        baseline = self.baselines.get(topic)
        if baseline is None:
            raise LookupError(f"notification topic {topic} has no baseline")
        now = self._clock()
        lease = now + timedelta(seconds=lease_seconds)
        out: list[Reservation] = []
        for item in items:
            subject, occurrence = str(item["subject"]), str(item["occurrence"])
            revision, fact_at = str(item["revision"]), _as_datetime(item["fact_at"])
            key = (topic, subject, occurrence)
            row = self.rows.get(key)
            if row is None:
                suppressed = fact_at < baseline
                self.rows[key] = _Row(
                    topic, subject, occurrence, revision, fact_at,
                    status="suppressed" if suppressed else "reserved",
                    owner=None if suppressed else owner,
                    lease_until=None if suppressed else lease,
                    first_seen_at=now, updated_at=now,
                )
                if suppressed:
                    self.deliveries.append({"key": key, "action": "suppress", "outcome": "suppressed"})
                out.append(Reservation(subject, occurrence, "suppressed" if suppressed else "create"))
                continue
            reclaimable = (
                (row.status == "reserved" and row.lease_until is not None and row.lease_until < now)
                or (row.status == "failed" and (row.retry_at is None or row.retry_at <= now))
                or (revisable and row.status == "sent" and row.sent_revision != revision)
                or (revisable and row.status == "suppressed" and row.revision != revision)
            )
            if reclaimable:
                row.status, row.owner, row.lease_until = "reserved", owner, lease
                row.revision, row.updated_at = revision, now
                out.append(Reservation(
                    subject, occurrence, "create" if row.message_id is None else "edit",
                    row.location_id, row.message_id, row.attempts,
                ))
            elif not revisable and row.status in {"sent", "suppressed"} and row.revision != revision:
                row.revision, row.updated_at = revision, now
        return out

    def begin_send(self, topic: str, keys: Sequence[tuple[str, str]], *, owner: str) -> int:
        now = self._clock()
        count = 0
        for subject, occurrence in keys:
            row = self.rows.get((topic, subject, occurrence))
            if (row is not None and row.owner == owner and row.status == "reserved"
                    and row.lease_until is not None and row.lease_until >= now):
                row.status, row.updated_at = "sending", now
                count += 1
        return count

    def finish(self, topic: str, keys: Sequence[tuple[str, str]], *, owner: str, action: str,
               outcome: str, location_id: str | None, message_id: str | None,
               failure_code: str | None, retry_seconds: int | None) -> int:
        if action not in {"create", "edit"}:
            raise ValueError("finish action must be create or edit")
        if outcome not in OUTCOMES:
            raise ValueError("finish outcome must be sent, failed, abandoned or unknown")
        now = self._clock()
        count = 0
        for subject, occurrence in keys:
            row = self.rows.get((topic, subject, occurrence))
            if row is None or row.owner != owner or row.status not in {"reserved", "sending"}:
                continue
            row.status, row.owner, row.lease_until = outcome, None, None
            row.attempts += 1
            row.retry_at = now + timedelta(seconds=max(retry_seconds or 60, 1)) if outcome == "failed" else None
            row.location_id = location_id or row.location_id
            row.message_id = message_id or row.message_id
            if outcome == "sent":
                if row.location_id is None or row.message_id is None:
                    raise ValueError("sent notice needs a location and a message")
                row.sent_revision, row.failure_code = row.revision, None
            else:
                row.failure_code = failure_code
            row.updated_at = now
            self.deliveries.append({"key": (topic, subject, occurrence), "action": action, "outcome": outcome})
            count += 1
        return count

    def replay(self, topic: str, subject: str, occurrence: str) -> int:
        row = self.rows.get((topic, subject, occurrence))
        if row is None or row.status not in {"sent", "suppressed", "abandoned", "unknown", "sending"}:
            return 0
        now = self._clock()
        row.status, row.retry_at, row.owner, row.lease_until, row.updated_at = "failed", now, None, None, now
        return 1

    def stuck_sending(self, *, older_than_seconds: int = STUCK_SENDING_SECONDS) -> list[tuple[str, str, str]]:
        cutoff = self._clock() - timedelta(seconds=older_than_seconds)
        return sorted(key for key, row in self.rows.items() if row.status == "sending" and row.updated_at < cutoff)

    def last_known(self, topic: str, subject: str) -> KnownNotice | None:
        known = [row for row in self.rows.values()
                 if row.topic == topic and row.subject == subject and row.status in {"sent", "suppressed"}]
        if not known:
            return None
        latest = max(known, key=lambda row: (row.first_seen_at, row.occurrence))
        revision = latest.sent_revision if latest.status == "sent" else latest.revision
        return KnownNotice(latest.occurrence, revision or "")

    def states(self, topic: str, keys: Sequence[tuple[str, str]]) -> dict[tuple[str, str], NoticeState]:
        out = {}
        for subject, occurrence in keys:
            row = self.rows.get((topic, subject, occurrence))
            if row is not None:
                out[(subject, occurrence)] = NoticeState(row.status, row.revision, row.sent_revision)
        return out

    def thread(self, channel_id: str, thread_key: str) -> str | None:
        return self.threads.get((channel_id, thread_key))

    def remember_thread(self, channel_id: str, thread_key: str, thread_id: str) -> None:
        self.threads[(channel_id, thread_key)] = thread_id

    def status(self, topic: str, subject: str, occurrence: str) -> str | None:
        row = self.rows.get((topic, subject, occurrence))
        return None if row is None else row.status

    def expire_lease(self, topic: str, subject: str, occurrence: str) -> None:
        """테스트가 시간을 건너뛰지 않고 만료된 예약을 만든다."""
        row = self.rows[(topic, subject, occurrence)]
        self.rows[(topic, subject, occurrence)] = replace(row, lease_until=self._clock() - timedelta(seconds=1))


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("fact_at must be timezone-aware")
    return moment


__all__ = [
    "ACTIONS", "MAX_LEASE_SECONDS", "MIN_LEASE_SECONDS", "MemoryLedger", "NotificationLedger",
    "OUTCOMES", "KnownNotice", "NoticeState", "Reservation",
]
