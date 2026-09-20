"""KR 기준금리 공식 일정이 만료되면 빈 일정이 아니라 오류로 드러난다(HC-1)."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.macro.domain.releases import schedule


class KrBaseRateCalendarExpiryTest(unittest.TestCase):
    def test_window_inside_the_calendar_returns_dates(self) -> None:
        got = schedule.official_calendar_dates("KR_BASE_RATE", start=date(2026, 1, 1), end=date(2026, 3, 1))
        self.assertEqual(got, [date(2026, 1, 15), date(2026, 2, 26)])

    def test_window_after_the_last_known_date_is_an_error(self) -> None:
        with self.assertRaises(schedule.ScheduleContractError):
            schedule.official_calendar_dates("KR_BASE_RATE", start=date(2027, 1, 1), end=date(2027, 12, 31))

    def test_window_that_reaches_past_the_end_still_returns_the_known_tail(self) -> None:
        got = schedule.official_calendar_dates("KR_BASE_RATE", start=date(2026, 11, 1), end=date(2027, 2, 1))
        self.assertEqual(got, [date(2026, 11, 26)])


if __name__ == "__main__":
    unittest.main()
