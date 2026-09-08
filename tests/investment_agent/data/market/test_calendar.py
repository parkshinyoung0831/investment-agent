"""확정 안 된 봉을 받지 않고, 날짜 경계를 뉴욕 기준으로 본다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from investment_agent.data.market.domain.calendar import (
    completed_bar_cutoff,
    market_today,
    overlap_window,
    session_of,
)


def _et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """뉴욕 시각을 UTC datetime으로. 테스트가 읽기 쉬우라고 둔다."""
    from zoneinfo import ZoneInfo

    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("America/New_York"))


class MarketTodayTest(unittest.TestCase):
    def test_utc_midnight_does_not_move_the_market_day(self) -> None:
        """UTC 자정 직후는 뉴욕에서 아직 전날이다."""
        self.assertEqual(
            date(2026, 9, 4),
            market_today(datetime(2026, 9, 5, 0, 30, tzinfo=timezone.utc)),
        )

    def test_naive_datetime_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            market_today(datetime(2026, 9, 5, 0, 30))


class CompletedBarCutoffTest(unittest.TestCase):
    def test_before_the_evening_cut_today_is_not_final(self) -> None:
        """장중 일봉은 종가가 아니라 현재가다. 그것을 적재하면 조용히 틀린다."""
        self.assertEqual(date(2026, 9, 3), completed_bar_cutoff(_et(2026, 9, 4, 11, 0)))

    def test_right_after_the_close_is_still_not_final(self) -> None:
        """16:00 이후에도 소스가 값을 손보는 일이 흔하다."""
        self.assertEqual(date(2026, 9, 3), completed_bar_cutoff(_et(2026, 9, 4, 16, 30)))

    def test_after_the_evening_cut_today_counts(self) -> None:
        self.assertEqual(date(2026, 9, 4), completed_bar_cutoff(_et(2026, 9, 4, 18, 1)))

    def test_exactly_at_the_cut_counts(self) -> None:
        self.assertEqual(date(2026, 9, 4), completed_bar_cutoff(_et(2026, 9, 4, 18, 0)))


class SessionTest(unittest.TestCase):
    def test_the_three_windows(self) -> None:
        self.assertEqual("bmo", session_of(_et(2026, 9, 4, 7, 0)))
        self.assertEqual("dmh", session_of(_et(2026, 9, 4, 12, 0)))
        self.assertEqual("amc", session_of(_et(2026, 9, 4, 16, 5)))

    def test_the_boundaries_belong_to_the_session_they_open(self) -> None:
        self.assertEqual("dmh", session_of(_et(2026, 9, 4, 9, 30)))
        self.assertEqual("amc", session_of(_et(2026, 9, 4, 16, 0)))


class OverlapWindowTest(unittest.TestCase):
    def test_window_ends_at_the_confirmed_cutoff(self) -> None:
        start, end = overlap_window(7, _et(2026, 9, 4, 11, 0))
        self.assertEqual(date(2026, 9, 3), end)
        self.assertEqual(date(2026, 8, 28), start)

    def test_one_day_window_is_a_single_day(self) -> None:
        start, end = overlap_window(1, _et(2026, 9, 4, 20, 0))
        self.assertEqual(start, end)

    def test_zero_days_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            overlap_window(0, _et(2026, 9, 4, 20, 0))


if __name__ == "__main__":
    unittest.main()
