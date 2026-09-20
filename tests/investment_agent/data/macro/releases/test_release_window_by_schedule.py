"""발표 창은 발표 시각으로 거른다(DA-1). 관측 기간(ref_period)으로 거르면 월간·주간 발표가 빠진다."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.data.macro.releases import db

UTC = timezone.utc


def _schedule(scheduled_at: str) -> dict:
    return {"scheduled_at": scheduled_at}


class EventsScheduledWithinTest(unittest.TestCase):
    def setUp(self) -> None:
        # 실제 운영에서 본 모양: CPI(월간)는 ref가 전월 1일, 청구(주간)는 발표 5일 전.
        self.events = [
            {"series_id": "US_CPI", "ref_period": "2026-08-01"},
            {"series_id": "US_INITIAL_CLAIMS", "ref_period": "2026-09-12"},
            {"series_id": "US_GDP", "ref_period": "2026-07-01"},
        ]
        self.schedules = {
            ("US_CPI", "2026-08-01"): _schedule("2026-09-11T12:30:00+00:00"),
            ("US_INITIAL_CLAIMS", "2026-09-12"): _schedule("2026-09-17T12:30:00+00:00"),
            ("US_GDP", "2026-07-01"): _schedule("2026-10-29T12:30:00+00:00"),
        }

    def _pick(self, start: str, end: str) -> list[str]:
        rows = db._events_scheduled_within(
            self.events, self.schedules,
            start=datetime.fromisoformat(start), end=datetime.fromisoformat(end),
        )
        return [row["series_id"] for row in rows]

    def test_monthly_release_is_found_by_its_release_time_not_its_reference_month(self) -> None:
        self.assertEqual(self._pick("2026-09-10T00:00:00+00:00", "2026-09-12T00:00:00+00:00"), ["US_CPI"])

    def test_weekly_release_is_found_when_the_watch_window_covers_its_release_time(self) -> None:
        self.assertEqual(self._pick("2026-09-13T12:45:00+00:00", "2026-09-17T12:45:00+00:00"), ["US_INITIAL_CLAIMS"])

    def test_event_without_a_schedule_is_skipped(self) -> None:
        del self.schedules[("US_GDP", "2026-07-01")]
        self.assertEqual(self._pick("2026-01-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00"),
                         ["US_CPI", "US_INITIAL_CLAIMS"])


if __name__ == "__main__":
    unittest.main()
