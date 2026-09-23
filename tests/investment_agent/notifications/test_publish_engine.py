"""알림 발행 엔진의 계약 — 같은 알림은 몇 번을 불러도 사람에게 한 번 닿는다.

원장은 SQL 함수와 같은 규칙을 따르는 MemoryLedger로 대신한다. 네트워크·Supabase 없음.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.notifications.channels.contracts import (
    Delivery,
    DeliveryRejected,
    DeliveryUnknown,
    ForumThread,
)
from investment_agent.notifications.engine import (
    MAX_ATTEMPTS,
    Notice,
    PublishContext,
    Rendered,
    publish,
)
from investment_agent.notifications.ledger import MemoryLedger
from investment_agent.notifications.problems import take_problems
from investment_agent.notifications.topics import Topic

BASE = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


class FakeChannel:
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
        self.created.append({"target": target, "message": message, "thread": thread,
                             "known_thread_id": known_thread_id, "nonce": nonce})
        message_id = self._id()
        if thread is None:
            return Delivery(target, message_id)
        thread_id = known_thread_id or message_id
        return Delivery(thread_id, message_id, thread_id)

    def edit(self, *, location_id, message_id, message, attachment_path=None):
        if self.failures:
            raise self.failures.pop(0)
        self.edited.append({"location_id": location_id, "message_id": message_id, "message": message})
        return Delivery(location_id, message_id)


def _notice(subject: str, occurrence: str = "1", *, value: object = 1, fact_at: datetime | None = None) -> Notice:
    return Notice(subject, occurrence, fact_at or BASE, {"value": value})


def _render(notices: list[Notice]) -> Rendered:
    return Rendered({"content": ",".join(f"{n.subject}={n.basis['value']}" for n in notices)})


class PublishEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = BASE + timedelta(hours=1)
        self.ledger = MemoryLedger(clock=lambda: self.now)
        self.channel = FakeChannel()
        take_problems()
        self.addCleanup(take_problems)

    def _publish(self, topic: Topic, notices, render=_render, owner: str = "run-1"):
        self.ledger.ensure_baseline(topic.name, BASE - timedelta(days=1))
        return publish(topic, notices, render,
                       context=PublishContext(self.ledger, self.channel, owner), target="42")

    def test_the_same_notices_reach_people_once_across_runs_and_runners(self) -> None:
        topic = Topic("test.event", "econ_calendar_release", batch_size=2)
        notices = [_notice("C"), _notice("A"), _notice("B")]

        first = self._publish(topic, notices, owner="actions")
        again = [self._publish(topic, notices, owner=owner) for owner in ("local", "safety-net", "manual")]

        self.assertEqual(first.created, 2)  # A,B 한 메시지 + C 한 메시지
        self.assertEqual([c["message"]["content"] for c in self.channel.created], ["A=1,B=1", "C=1"])
        self.assertEqual([report.delivered for report in again], [0, 0, 0])
        # 보내지 않은 이유가 보고에 남는다 — 후보가 어느 칸에도 안 세지면 "사라진 알림"처럼 읽힌다.
        self.assertEqual([report.already_recorded for report in again], [3, 3, 3])
        self.assertEqual(take_problems(), ())

    def test_a_topic_without_a_baseline_refuses_to_send(self) -> None:
        topic = Topic("test.unbaselined", "econ_calendar_release")

        with self.assertRaises(LookupError):
            publish(topic, [_notice("A")], _render,
                    context=PublishContext(self.ledger, self.channel, "run"), target="42")
        self.assertEqual(self.channel.created, [])

    def test_facts_from_before_the_baseline_are_recorded_but_not_sent(self) -> None:
        topic = Topic("test.event", "econ_calendar_release")

        report = self._publish(topic, [_notice("OLD", fact_at=BASE - timedelta(days=30)), _notice("NEW")])

        self.assertEqual((report.suppressed, report.created), (1, 1))
        self.assertEqual(self.ledger.status("test.event", "OLD", "1"), "suppressed")
        self.assertEqual([c["message"]["content"] for c in self.channel.created], ["NEW=1"])

    def test_an_event_topic_ignores_later_changes(self) -> None:
        topic = Topic("test.event", "econ_calendar_release")
        self._publish(topic, [_notice("A", value=1)])

        report = self._publish(topic, [_notice("A", value=2)])

        self.assertEqual((report.created, report.edited), (0, 0))
        self.assertEqual(self.channel.edited, [])

    def test_a_revisable_topic_edits_the_message_people_already_have(self) -> None:
        topic = Topic("test.digest", "macro_core", on_revision="edit")
        self._publish(topic, [_notice("market", "2026-09-13", value=1)])
        sent = self.channel.created[0]

        report = self._publish(topic, [_notice("market", "2026-09-13", value=2)])
        unchanged = self._publish(topic, [_notice("market", "2026-09-13", value=2)])

        self.assertEqual(report.edited, 1)
        self.assertEqual(len(self.channel.created), 1)
        self.assertEqual(self.channel.edited[0]["message"]["content"], "market=2")
        self.assertEqual(self.channel.edited[0]["location_id"], sent["target"])
        self.assertEqual(unchanged.delivered, 0)

    def test_skip_unchanged_does_not_repeat_yesterdays_digest(self) -> None:
        topic = Topic("test.digest", "macro_core", on_revision="edit", skip_unchanged=True)
        self._publish(topic, [_notice("market", "2026-09-12", value=1)])

        same = self._publish(topic, [_notice("market", "2026-09-13", value=1)])
        changed = self._publish(topic, [_notice("market", "2026-09-14", value=5)])

        self.assertEqual((same.unchanged, same.created), (1, 0))
        self.assertEqual(changed.created, 1)

    def test_a_state_suppressed_at_the_baseline_counts_as_already_known(self) -> None:
        """원장 도입 전에 옛 경로가 보낸 상태를 전환 다음 날 다시 알리지 않는다."""
        topic = Topic("test.state", "macro_watch", skip_unchanged=True)
        before_baseline = BASE - timedelta(days=2)
        self._publish(topic, [_notice("VIX", "2026-09-11", value="alert", fact_at=before_baseline)])

        next_day = self._publish(topic, [_notice("VIX", "2026-09-14", value="alert")])
        changed = self._publish(topic, [_notice("VIX", "2026-09-15", value="clear")])

        self.assertEqual((next_day.unchanged, next_day.created), (1, 0))
        self.assertEqual(changed.created, 1)

    def test_replay_redraws_the_same_message_in_place(self) -> None:
        topic = Topic("test.event", "econ_calendar_release")
        self._publish(topic, [_notice("A")])

        self.assertEqual(self.ledger.replay(topic.name, "A", "1"), 1)
        report = self._publish(topic, [_notice("A")])

        self.assertEqual((report.created, report.edited), (0, 1))
        self.assertEqual(self.channel.edited[0]["message_id"], "1001")

    def test_a_render_failure_is_retried_later_and_then_abandoned(self) -> None:
        topic = Topic("test.event", "econ_calendar_release")

        def broken(_notices):
            raise RuntimeError("template bug")

        for attempt in range(1, MAX_ATTEMPTS + 1):
            report = self._publish(topic, [_notice("A")], render=broken)
            self.assertEqual(report.failed, 1, attempt)
            self.now += timedelta(hours=1)

        self.assertEqual(self.ledger.status("test.event", "A", "1"), "abandoned")
        self.assertEqual(self._publish(topic, [_notice("A")]).delivered, 0)
        self.assertEqual([p.status for p in take_problems()], ["failed", "failed", "abandoned"])

    def test_a_rate_limit_is_retried_after_its_interval(self) -> None:
        topic = Topic("test.event", "econ_calendar_release")
        self.channel.failures.append(DeliveryRejected("discord_rate_limited", is_retryable=True, retry_after=30))

        first = self._publish(topic, [_notice("A")])
        too_soon = self._publish(topic, [_notice("A")])
        self.now += timedelta(seconds=31)
        later = self._publish(topic, [_notice("A")])

        self.assertEqual((first.failed, too_soon.delivered, later.created), (1, 0, 1))
        self.assertEqual(take_problems(), ())

    def test_a_rate_limit_never_uses_up_the_attempts(self) -> None:
        """정정이 잦은 카드는 성공한 전송만으로 시도 횟수가 찬다. 속도 제한 한 번에 영구 포기하면 안 된다."""
        topic = Topic("test.event", "econ_calendar_release")
        for _ in range(4):
            self.channel.failures.append(
                DeliveryRejected("discord_rate_limited", is_retryable=True, retry_after=30, is_throttled=True))
            self.assertEqual(1, self._publish(topic, [_notice("A")]).failed)
            self.now += timedelta(seconds=31)

        self.assertEqual(1, self._publish(topic, [_notice("A")]).created)
        self.assertEqual(take_problems(), ())

    def test_a_rejection_or_unknown_outcome_is_reported_and_never_resent_automatically(self) -> None:
        topic = Topic("test.event", "econ_calendar_release")
        self.channel.failures.extend([DeliveryRejected("discord_http_403"), DeliveryUnknown("timeout"), DeliveryUnknown("timeout")])

        self._publish(topic, [_notice("A"), _notice("B")])
        self.now += timedelta(days=1)
        later = self._publish(topic, [_notice("A"), _notice("B")])

        self.assertEqual(later.delivered, 0)
        self.assertEqual(sorted(p.status for p in take_problems()), ["abandoned", "unknown"])
        self.assertEqual(self.ledger.status("test.event", "A", "1"), "abandoned")
        self.assertEqual(self.ledger.status("test.event", "B", "1"), "unknown")

    def test_a_lost_response_is_asked_again_with_the_same_nonce(self) -> None:
        topic = Topic("test.event", "econ_calendar_release")
        self.channel.failures.append(DeliveryUnknown("timeout"))

        report = self._publish(topic, [_notice("A")])

        self.assertEqual(report.created, 1)
        self.assertEqual(self.ledger.status("test.event", "A", "1"), "sent")

    def test_an_expired_reservation_is_not_sent_by_its_old_owner(self) -> None:
        topic = Topic("test.event", "econ_calendar_release")
        self.ledger.ensure_baseline(topic.name, BASE - timedelta(days=1))
        stolen = []

        def render_slowly(notices):
            self.ledger.expire_lease(topic.name, "A", "1")
            stolen.extend(self.ledger.reserve(topic.name, [{
                "subject": "A", "occurrence": "1", "revision": notices[0].revision, "fact_at": BASE,
            }], owner="other-run", lease_seconds=60, revisable=False))
            return _render(notices)

        report = publish(topic, [_notice("A")], render_slowly,
                         context=PublishContext(self.ledger, self.channel, "slow-run"), target="42")

        self.assertEqual(report.delivered, 0)
        self.assertEqual(len(stolen), 1)
        self.assertEqual(self.channel.created, [])

    def test_forum_threads_are_remembered_and_reused(self) -> None:
        topic = Topic("test.forum", "fundamentals_flash")

        def forum(notices):
            return Rendered({"content": notices[0].occurrence}, thread=ForumThread("AVGO", "AVGO · Broadcom · 실적 기록"))

        self._publish(topic, [_notice("AVGO", "8-K")], render=forum)
        self._publish(topic, [_notice("AVGO", "10-Q")], render=forum)

        first, second = self.channel.created
        self.assertIsNone(first["known_thread_id"])
        # 첫 전송이 만든 스레드(FakeChannel은 첫 메시지 id를 스레드 id로 쓴다)를 두 번째가 받는다.
        self.assertEqual(second["known_thread_id"], "1001")
        self.assertEqual(self.ledger.thread("42", "AVGO"), "1001")

    def test_conflicting_notices_for_one_identity_are_refused(self) -> None:
        topic = Topic("test.event", "econ_calendar_release")

        with self.assertRaises(ValueError):
            self._publish(topic, [_notice("A", value=1), _notice("A", value=2)])

    def test_batched_topics_cannot_be_revisable(self) -> None:
        with self.assertRaises(ValueError):
            Topic("test.bad", "macro_watch", on_revision="edit", batch_size=3)


if __name__ == "__main__":
    unittest.main()
