"""경제 캘린더와 v1 macro watch의 dedup 의미를 검증한다."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from investment_agent.notifications.econ_calendar import run as release_run
from investment_agent.notifications.macro import watch as macro_watch


def _row(series_id: str, obs_date: str) -> dict:
    return {
        "series_id": series_id, "name_ko": "테스트지표", "category": "inflation",
        "unit": "%", "series_kind": "", "frequency": "monthly", "obs_date": obs_date,
        "curr": 1.0, "prev_value": 1.0, "metrics": {}, "prev_metrics": {}, "spark": [],
        "freshness": {"state": "fresh", "obs_date": obs_date, "age_days": 0},
    }


class ReleaseDedupTest(unittest.TestCase):
    def test_no_pending_sends_and_marks_nothing(self):
        config = mock.Mock()
        config.require.return_value = ("123",)
        with mock.patch.object(release_run, "load_config", return_value=config), \
             mock.patch.object(release_run, "configured_database", return_value=mock.Mock()), \
             mock.patch.object(release_run.store, "load_pending", return_value=[]), \
             mock.patch.object(release_run, "NotificationService") as service:
            release_run.run()
        service.return_value.run_pending.assert_not_called()

    def test_marks_every_row_that_was_sent(self):
        rows = [
            {**_row("US_CPI", "2026-08-12"), "event_key": "US_CPI:2026-07-01", "ref_period": "2026-07-01"},
            {**_row("US_UNEMPLOYMENT", "2026-08-13"), "event_key": "US_UNEMPLOYMENT:2026-07-01", "ref_period": "2026-07-01"},
        ]
        config = mock.Mock()
        config.require.return_value = ("123",)
        with mock.patch.object(release_run, "load_config", return_value=config), \
             mock.patch.object(release_run, "configured_database", return_value=mock.Mock()), \
             mock.patch.object(release_run.store, "load_pending", return_value=rows), \
             mock.patch.object(release_run, "NotificationService") as service:
            service.return_value.run_pending.return_value = [SimpleNamespace(status="sent")]
            self.assertEqual(release_run.run(targets=("123",)), 1)
        service.return_value.enqueue.assert_called_once()

    def test_send_failure_leaves_the_row_unmarked(self):
        rows = [{**_row("US_CPI", "2026-08-12"), "event_key": "US_CPI:2026-07-01", "ref_period": "2026-07-01"}]
        config = mock.Mock()
        config.require.return_value = ("123",)
        with mock.patch.object(release_run, "load_config", return_value=config), \
             mock.patch.object(release_run, "configured_database", return_value=mock.Mock()), \
             mock.patch.object(release_run.store, "load_pending", return_value=rows), \
             mock.patch.object(release_run, "NotificationService") as service:
            service.return_value.run_pending.return_value = [SimpleNamespace(status="unknown")]
            self.assertEqual(release_run.run(targets=("123",)), 0)
        service.return_value.enqueue.assert_called_once()


class WatchDedupTest(unittest.TestCase):
    def setUp(self):
        self.store = mock.Mock()
        self.service = mock.Mock()
        self.service.enqueue.return_value = mock.Mock(status="enqueued")

    def test_no_pending_obs_sends_nothing(self):
        self.store.load_watch_pending.return_value = []
        macro_watch.run(store=self.store, service=self.service, targets=("123",))
        self.service.enqueue.assert_not_called()
        self.service.run_pending.assert_not_called()

    def test_no_threshold_does_not_create_an_outbox_message(self):
        rows = [_row("A", "2026-08-12"), _row("B", "2026-08-12")]
        self.store.load_watch_pending.return_value = rows
        with mock.patch.object(macro_watch, "eval_row", return_value=(None, None)):
            macro_watch.run(store=self.store, service=self.service, targets=("123",))
        self.service.enqueue.assert_not_called()

    def test_thresholded_rows_are_enqueued_as_one_card(self):
        rows = [_row("A", "2026-08-12"), _row("B", "2026-08-12")]
        self.store.load_watch_pending.return_value = rows
        tiers = {"A": ("🔴 alert", "z=+5.00"), "B": (None, None)}
        with mock.patch.object(macro_watch, "eval_row", side_effect=lambda r: tiers[r["series_id"]]), \
             mock.patch.object(macro_watch.embeds, "build_watch", return_value={"fields": []}), \
             mock.patch.object(macro_watch, "load_config") as config:
            config.return_value.require.return_value = ("123",)
            macro_watch.run(store=self.store, service=self.service, targets=("123",))
        self.service.enqueue.assert_called_once()
        self.assertEqual("macro_watch", self.service.enqueue.call_args.kwargs["kind"])
        self.service.run_pending.assert_called_once()


if __name__ == "__main__":
    unittest.main()
