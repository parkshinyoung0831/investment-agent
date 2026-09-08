"""자연키·구독 UID·일정 변경을 보존하는 ECON ICS 테스트."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.data.macro.infrastructure.releases import ics


class EconIcsTest(unittest.TestCase):
    def _row(self, **changes) -> dict:
        return {"series_id": "KR_BASE_RATE", "ref_period": "2026-08-27", "series_name_ko": "한국 기준금리",
                "measure_name_ko": "기준금리", "scheduled_at": "2026-08-27T00:50:00Z",
                "timezone": "Asia/Seoul", "schedule_confidence": "exact", **changes}

    def test_natural_uid_is_stable_when_schedule_is_postponed(self) -> None:
        first = ics.build([self._row()])
        second = ics.build([self._row(scheduled_at="2026-08-28T00:50:00Z")])
        uid = "UID:KR_BASE_RATE:2026-08-27@econ-calendar.investment-agent"
        self.assertIn(uid, first)
        self.assertIn(uid, second)
        self.assertIn("DTSTART:20260827T005000Z", first)
        self.assertIn("DTSTART:20260828T005000Z", second)

    def test_date_only_uses_the_series_timezone(self) -> None:
        text = ics.build([self._row(series_id="US_GDP", ref_period="2026-07-01",
            scheduled_at="2026-08-01T01:00:00Z", timezone="America/New_York", schedule_confidence="date_only")])
        self.assertIn("DTSTART;VALUE=DATE:20260731", text)
        self.assertIn("STATUS:TENTATIVE", text)

    def test_cancelled_event_keeps_its_identity(self) -> None:
        text = ics.build([self._row(status="cancelled")])
        self.assertIn("STATUS:CANCELLED", text)
        self.assertNotIn("STATUS:CONFIRMED", text)

    def test_group_events_deduplicates_by_series_and_period(self) -> None:
        rows = [self._row(), self._row(scheduled_at="2026-08-28T00:50:00Z"), self._row(ref_period="2026-10-15")]
        self.assertEqual([row["ref_period"] for row in ics.group_events(rows)], ["2026-08-27", "2026-10-15"])

    def test_naive_schedule_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ics.build([self._row(scheduled_at="2026-08-27T00:50:00")])


if __name__ == "__main__":
    unittest.main()
