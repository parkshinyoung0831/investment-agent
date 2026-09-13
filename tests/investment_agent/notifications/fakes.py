"""알림 테스트가 함께 쓰는 가짜 Discord 채널과 메모리 원장. 네트워크·Supabase 없음."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from investment_agent.notifications.channels.discord import Delivery
from investment_agent.notifications.engine import PublishContext
from investment_agent.notifications.ledger import MemoryLedger
from investment_agent.notifications.topics import TOPICS


class FakeChannel:
    """보낸 메시지를 기록한다. failures에 넣은 예외를 차례로 던진다."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.edited: list[dict] = []
        self.failures: list[Exception] = []
        self._next_id = 1000

    def _id(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    def deliver(self, *, target, message, attachment_path=None, thread=None, known_thread_id=None, nonce=None):
        if self.failures:
            raise self.failures.pop(0)
        self.created.append({"target": target, "message": message, "attachment_path": attachment_path,
                             "thread": thread, "known_thread_id": known_thread_id, "nonce": nonce})
        message_id = self._id()
        if thread is None:
            return Delivery(target, message_id)
        thread_id = known_thread_id or message_id
        return Delivery(thread_id, message_id, thread_id)

    def edit(self, *, location_id, message_id, message, attachment_path=None):
        if self.failures:
            raise self.failures.pop(0)
        self.edited.append({"location_id": location_id, "message_id": message_id, "message": message,
                            "attachment_path": attachment_path})
        return Delivery(location_id, message_id)


def memory_context(*, baseline: datetime | None = None, clock=None,
                   owner: str = "test-run") -> tuple[PublishContext, MemoryLedger, FakeChannel]:
    """모든 topic의 baseline을 과거로 둔 메모리 원장과 가짜 채널."""
    ledger = MemoryLedger(clock=clock)
    start = baseline or datetime(2000, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
    for name in TOPICS:
        ledger.ensure_baseline(name, start)
    channel = FakeChannel()
    return PublishContext(ledger, channel, owner), ledger, channel


__all__ = ["FakeChannel", "memory_context"]
