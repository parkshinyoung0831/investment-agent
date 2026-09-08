"""실제 로컬 SQLite로 원자적 선점·전송·실패 보존을 검증한다."""
from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from investment_agent.notifications.channels.discord import DeliveryRejected, DeliveryUnknown
from investment_agent.notifications.outbox import Outbox
from investment_agent.notifications.service import NotificationService
from investment_agent.platform.db.sqlite import runtime_connection

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


class NotificationServiceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "runtime.sqlite3"
        env = patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(self.path)})
        env.start()
        self.addCleanup(env.stop)
        self.outbox = Outbox()
        self.channel = Mock()
        self.channel.send.return_value = "12345"
        self.now = NOW
        self.service = NotificationService(self.outbox, self.channel, clock=lambda: self.now)
        self.args = dict(producer="test", notification_key="key:123", kind="report", target="123", message={"content": "보고서예요"})

    def enqueue(self):
        return self.service.enqueue(**self.args)

    def row(self):
        return self.outbox.get("test", "key:123")

    def deliveries(self, producer="test", notification_key="key:123"):
        with runtime_connection(read_only=True) as connection:
            rows = connection.execute(
                "SELECT status,failure_reason FROM notification_deliveries "
                "WHERE producer=? AND notification_key=? ORDER BY delivery_id",
                (producer, notification_key),
            ).fetchall()
        return [{"status": status, "failure_reason": reason} for status, reason in rows]

    def test_enqueue_is_not_send_and_duplicate_cannot_overwrite(self):
        self.assertEqual("enqueued", self.enqueue().status)
        self.assertEqual("duplicate", self.enqueue().status)
        self.channel.send.assert_not_called()
        self.args["message"]["content"] = "changed"
        self.assertEqual("error", self.enqueue().status)
        self.assertEqual("보고서예요", self.row()["payload"]["message"]["content"])

    def test_success_is_recorded_before_outbox_completion(self):
        self.enqueue()
        result, = self.service.run_pending()
        self.assertEqual("sent", result.status)
        self.assertEqual("sent", self.row()["status"])
        self.assertEqual(1, self.row()["attempt_count"])
        delivery, = self.deliveries()
        self.assertEqual("sent", delivery["status"])
        self.assertIsNone(delivery["failure_reason"])
        self.assertEqual([], self.service.run_pending())
        self.channel.send.assert_called_once()

    def test_attachment_snapshot_uses_file_sender_and_is_recorded(self):
        result = self.service.enqueue(**self.args, attachment_path="artifacts/macro_core.png")
        self.assertEqual("enqueued", result.status)
        self.channel.send_file.return_value = "12345"
        self.assertEqual("sent", self.service.run_pending()[0].status)
        self.channel.send.assert_not_called()
        self.channel.send_file.assert_called_once_with(
            target="123", path="artifacts/macro_core.png", content="보고서예요",
        )

    def test_two_workers_can_only_send_once(self):
        self.enqueue()
        row = self.row()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.service.dispatch, [row, row]))
        self.assertEqual(["sent", "skipped"], sorted(r.status for r in results))
        self.channel.send.assert_called_once()

    def test_rate_limit_retries_after_wait_and_preserves_failures(self):
        self.enqueue()
        self.channel.send.side_effect = DeliveryRejected("rate", is_retryable=True, retry_after=120)
        self.assertEqual("failed", self.service.run_pending()[0].status)
        self.now += timedelta(seconds=119)
        self.assertEqual([], self.service.run_pending())
        self.now += timedelta(seconds=1)
        self.channel.send.side_effect = None
        self.assertEqual("sent", self.service.run_pending()[0].status)
        self.assertEqual(["failed", "sent"], [row["status"] for row in self.deliveries()])
        self.assertEqual(2, self.row()["attempt_count"])
        self.assertEqual(self.channel.send.call_args_list[0], self.channel.send.call_args_list[1])
        self.assertEqual("duplicate", self.enqueue().status)

    def test_retry_limit_abandons_without_deleting_history(self):
        self.enqueue()
        self.channel.send.side_effect = DeliveryRejected("rate", is_retryable=True)
        for expected in ("failed", "failed", "abandoned"):
            self.assertEqual(expected, self.service.run_pending()[0].status)
            self.now += timedelta(minutes=1)
        self.assertEqual([], self.service.run_pending())
        self.assertEqual(3, len(self.deliveries()))

    def test_permanent_rejection_is_not_retried(self):
        self.enqueue()
        self.channel.send.side_effect = DeliveryRejected("forbidden")
        self.assertEqual("abandoned", self.service.run_pending()[0].status)
        self.assertEqual([], self.service.run_pending())

    def test_unknown_result_is_held_and_never_automatically_reclaimed(self):
        """전달 여부 불명 결과는 delivery 이력을 남기지 않고 outbox 행을 pending·claimed 상태로 묶어 둔다.

        ``Outbox.record``는 status가 ``unknown``이면 아무 것도 쓰지 않는다(outbox.py 참고) —
        확실하지 않은 결과를 sent/failed로 잘못 확정하지 않기 위해서다. 그 대신 이미
        ``claim()``이 늘려 둔 attempt_count가 ``ready()``의 selection에서 그 행을 제외시켜
        자동 재청구를 막는다.
        """
        for error in (TimeoutError("private"), DeliveryUnknown("unknown")):
            with self.subTest(error=type(error).__name__):
                self.setUp()
                self.enqueue()
                self.channel.send.side_effect = error
                result = self.service.run_pending()[0]
                self.assertEqual("unknown", result.status)
                self.assertIn("불명", result.reason)
                self.assertEqual("pending", self.row()["status"])
                self.assertIsNone(self.row()["resolved_at"])
                self.assertEqual([], self.deliveries())
                self.now += timedelta(days=365)
                self.assertEqual([], self.service.run_pending())
                self.assertIsNone(self.outbox.claim(self.row(), now=self.now, max_attempts=3))

    def test_claim_error_never_calls_sender(self):
        self.enqueue()
        with patch.object(self.outbox, "claim", side_effect=RuntimeError("token=private https://db.private")):
            self.assertEqual("error", self.service.run_pending()[0].status)
        self.channel.send.assert_not_called()

    def test_delivery_insert_error_after_send_does_not_resend(self):
        self.enqueue()
        with patch.object(self.outbox, "record", side_effect=RuntimeError("token=private https://db.private")):
            self.assertEqual("error", self.service.run_pending()[0].status)
        self.assertEqual([], self.service.run_pending())
        self.channel.send.assert_called_once()

    def test_completion_error_after_send_holds_the_row_without_resending(self):
        """record() 실패는 하나의 SQLite 트랜잭션을 통째로 되돌리므로 delivery만 남고
        outbox는 못 갱신되는 부분 상태는 생기지 않는다 — outbox 행이 claim()이 남긴
        pending·count=1 그대로 묶여 다시 전송되지 않는 것만 보장하면 된다."""
        self.enqueue()
        with patch.object(self.outbox, "record", side_effect=RuntimeError("token=private https://db.private")):
            self.assertEqual("error", self.service.run_pending()[0].status)
        self.assertEqual([], self.deliveries())
        self.assertEqual("pending", self.row()["status"])
        self.assertEqual(1, self.row()["attempt_count"])
        self.assertEqual([], self.service.run_pending())
        self.channel.send.assert_called_once()

    def test_enqueue_and_read_errors_are_visible_without_raising(self):
        with patch.object(self.outbox, "enqueue", side_effect=RuntimeError("token=private https://db.private")):
            result = self.enqueue()
        self.assertEqual("error", result.status)
        self.assertNotIn("private", result.reason)
        with patch.object(self.outbox, "ready", side_effect=RuntimeError("token=private https://db.private")):
            self.assertEqual("error", self.service.run_pending()[0].status)
        self.channel.send.assert_not_called()

    def test_stale_failed_row_cannot_claim_a_new_attempt(self):
        self.enqueue()
        self.channel.send.side_effect = DeliveryRejected("rate", is_retryable=True)
        self.service.run_pending()
        row = self.row()
        self.now += timedelta(minutes=1)
        self.assertEqual("failed", self.service.dispatch(row).status)
        self.assertEqual("skipped", self.service.dispatch(row).status)

    def test_pending_lookup_reads_beyond_one_page(self):
        for i in range(1005):
            self.args["notification_key"] = str(i)
            self.enqueue()
        self.assertEqual(1005, len(self.outbox.ready(now=NOW)))

    def test_invalid_message_is_not_enqueued(self):
        self.args["message"] = {"content": "x" * 2001}
        self.assertEqual("error", self.enqueue().status)
        self.assertFalse(self.path.exists(), "검증 실패는 원장 파일에 아무 흔적도 남기지 않아야 한다")

    def test_zero_retry_budget_is_invalid(self):
        for budget in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                NotificationService(self.outbox, self.channel, clock=lambda: NOW, max_attempts=budget)

    def test_period_end_and_sent_keys_and_filter_pending(self):
        self.service.enqueue(
            producer="test", notification_key="k1", kind="report",
            target="123", message={"content": "c1"}, period_end=date(2026, 9, 5),
        )
        self.assertEqual("2026-09-05", self.outbox.get("test", "k1")["period_end"])
        self.assertEqual({"k1"}, self.outbox.sent_keys("test"))
        self.assertEqual({"k1"}, self.outbox.sent_keys("test", kind="report"))
        self.assertEqual(set(), self.outbox.sent_keys("test", kind="other"))
        self.assertEqual(["k2"], self.outbox.filter_pending("test", ["k1", "k2"]))


if __name__ == "__main__":
    unittest.main()
