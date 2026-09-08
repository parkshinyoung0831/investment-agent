"""시간은 tz-aware만 받고, 읽을 수 없는 날짜는 예외 대신 None이다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from investment_agent.platform.clock import (
    FixedClock,
    SystemClock,
    as_date,
    day_window,
    ensure_aware,
    to_utc_iso,
)


class EnsureAwareTest(unittest.TestCase):
    def test_naive_datetime_is_rejected(self) -> None:
        """추측해서 넘어가면 자정 근처에서 날짜가 하루 밀린다."""
        with self.assertRaises(ValueError):
            ensure_aware(datetime(2026, 9, 5, 3, 0))

    def test_other_zone_is_converted_to_utc(self) -> None:
        seoul = datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc).astimezone(
            __import__("zoneinfo").ZoneInfo("Asia/Seoul")
        )
        self.assertEqual(timezone.utc, ensure_aware(seoul).tzinfo)
        self.assertEqual("2026-09-05T09:00:00+00:00", to_utc_iso(seoul))


class ClockTest(unittest.TestCase):
    def test_system_clock_is_timezone_aware(self) -> None:
        self.assertIsNotNone(SystemClock().now().tzinfo)

    def test_fixed_clock_repeats_the_same_instant(self) -> None:
        instant = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        clock = FixedClock(instant)
        self.assertEqual(instant, clock.now())
        self.assertEqual(clock.now(), clock.now())

    def test_fixed_clock_rejects_naive_instant(self) -> None:
        with self.assertRaises(ValueError):
            FixedClock(datetime(2026, 9, 5, 12, 0))


class AsDateTest(unittest.TestCase):
    def test_reads_the_shapes_that_actually_arrive(self) -> None:
        self.assertEqual(date(2026, 9, 5), as_date("2026-09-05"))
        self.assertEqual(date(2026, 9, 5), as_date("2026-09-05T13:20:00+00:00"))
        self.assertEqual(date(2026, 9, 5), as_date(datetime(2026, 9, 5, 13, 20, tzinfo=timezone.utc)))
        self.assertEqual(date(2026, 9, 5), as_date(date(2026, 9, 5)))

    def test_unreadable_values_are_none_not_exceptions(self) -> None:
        """한 행 때문에 배치 전체가 멈추면 안 된다."""
        for value in (None, "", "   ", "not-a-date", "2026-13-45"):
            self.assertIsNone(as_date(value), value)


class DayWindowTest(unittest.TestCase):
    def test_window_includes_the_end_day(self) -> None:
        self.assertEqual((date(2026, 8, 30), date(2026, 9, 5)), day_window(date(2026, 9, 5), 7))

    def test_single_day_window(self) -> None:
        self.assertEqual((date(2026, 9, 5), date(2026, 9, 5)), day_window(date(2026, 9, 5), 1))

    def test_zero_days_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            day_window(date(2026, 9, 5), 0)


if __name__ == "__main__":
    unittest.main()
