"""경제발표 사실과 v1 notifications outbox의 경계를 검증한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from investment_agent.notifications.econ_calendar import run
from investment_agent.notifications.econ_calendar import db as store


class NotificationLedgerTest(unittest.TestCase):
    def test_notification_key_is_natural_and_validated(self) -> None:
        self.assertEqual(store.notification_key("US_CPI:2026-07-01"), "first_actual:US_CPI:2026-07-01")
        with self.assertRaises(ValueError):
            store.notification_key("not-a-natural-key")

    def test_pending_uses_macro_reader_and_outbox_keys(self) -> None:
        now = datetime.now(timezone.utc)
        rows = [
            {"event_key": f"{sid}:2026-07-01", "series_id": sid, "status": "released",
             "first_actual_value": .2, "first_actual_at": (now - timedelta(days=1)).isoformat()}
            for sid in ("US_CPI", "US_CORE_CPI")
        ]
        outbox = Mock()
        outbox.filter_pending.return_value = [store.notification_key(rows[1]["event_key"])]
        store.configure(outbox, Mock())
        with patch.object(store._reporting, "read", return_value=Mock(status="ok", rows=rows)):
            pending = store.load_pending()
        self.assertEqual([row["series_id"] for row in pending], ["US_CORE_CPI"])
        outbox.filter_pending.assert_called_once()

    def test_run_enqueues_snapshot_before_dispatch(self) -> None:
        config = Mock()
        config.require.return_value = ("123",)
        database = Mock()
        outbox = Mock()
        service = Mock()
        service.run_pending.return_value = [Mock(status="sent")]
        rows = [{"event_key": "US_CPI:2026-07-01", "ref_period": "2026-07-01", "series_id": "US_CPI", "category": "inflation", "unit": "percent", "first_actual_value": 1.0}]
        with (
            patch.object(run, "load_config", return_value=config),
            patch.object(run, "configured_database", return_value=database),
            patch.object(run, "Outbox", return_value=outbox),
            patch.object(run.store, "load_pending", return_value=rows),
            patch.object(run, "NotificationService", return_value=service),
        ):
            self.assertEqual(run.run(target="123"), 1)
        service.enqueue.assert_called_once()
        service.run_pending.assert_called_once()


if __name__ == "__main__":
    unittest.main()
