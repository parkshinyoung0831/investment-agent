"""예정 시각이 지났는데 값이 없는 발표는 예정 목록에도 결과 목록에도 안 잡히므로 따로 읽는다(RP-06)."""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.reporting.models import DataResult
from investment_agent.reporting.readers import dashboard


def _window_rows(rows):
    return lambda start, end: DataResult.ok(rows=rows, source="test")


class PastDueTest(unittest.TestCase):
    def test_only_unresolved_releases_are_returned_newest_first(self):
        rows = [
            {"event_key": "a", "status": "released", "scheduled_at": "2026-09-10T12:30:00+00:00"},
            {"event_key": "b", "status": "not_available_yet", "scheduled_at": "2026-09-12T12:30:00+00:00"},
            {"event_key": "c", "status": "not_available_yet", "scheduled_at": "2026-09-15T12:30:00+00:00"},
            {"event_key": "d", "status": "scheduled", "scheduled_at": "2026-09-16T12:30:00+00:00"},
        ]
        with mock.patch.object(dashboard, "_window", side_effect=_window_rows(rows)):
            result = dashboard.load_econ_past_due(14)
        self.assertEqual(["c", "b"], [row["event_key"] for row in result.rows])

    def test_nothing_past_due_is_an_empty_result_not_an_error(self):
        with mock.patch.object(dashboard, "_window", side_effect=_window_rows([])):
            self.assertEqual("empty", dashboard.load_econ_past_due().status)

    def test_a_failed_read_is_passed_through(self):
        failed = DataResult.error(source="test", message="boom")
        with mock.patch.object(dashboard, "_window", return_value=failed):
            self.assertEqual("error", dashboard.load_econ_past_due().status)


if __name__ == "__main__":
    unittest.main()
