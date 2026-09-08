"""cron 판정 — 여기가 틀리면 '미실행'을 거꾸로 보고한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.operations.monitoring import cron

UTC = timezone.utc


class CronMatchTest(unittest.TestCase):
    def test_weekday_range_uses_cron_numbering(self):
        """cron 요일은 일=0이다. 파이썬 weekday()(월=0)를 그대로 쓰면 하루씩 밀린다."""
        tuesday = datetime(2026, 8, 18, 0, 25, tzinfo=UTC)
        monday = datetime(2026, 8, 17, 0, 25, tzinfo=UTC)
        sunday = datetime(2026, 8, 16, 0, 25, tzinfo=UTC)

        self.assertTrue(cron.matches("25 0 * * 2-6", tuesday))   # 화~토
        self.assertFalse(cron.matches("25 0 * * 2-6", monday))
        self.assertFalse(cron.matches("25 0 * * 2-6", sunday))
        self.assertTrue(cron.matches("25 0 * * 1", monday))      # 월 전용

    def test_hour_range_and_step(self):
        self.assertTrue(cron.matches("0 0-9 * * 1-5", datetime(2026, 8, 18, 9, 0, tzinfo=UTC)))
        self.assertFalse(cron.matches("0 0-9 * * 1-5", datetime(2026, 8, 18, 10, 0, tzinfo=UTC)))
        self.assertTrue(cron.matches("*/15 * * * *", datetime(2026, 8, 18, 3, 45, tzinfo=UTC)))

    def test_day_of_month_range(self):
        self.assertTrue(cron.matches("0 22 28-31 * *", datetime(2026, 8, 29, 22, 0, tzinfo=UTC)))
        self.assertFalse(cron.matches("0 22 28-31 * *", datetime(2026, 8, 27, 22, 0, tzinfo=UTC)))

    def test_rejects_non_five_field(self):
        with self.assertRaises(ValueError):
            cron.parse("0 22 * *")


class FiresBetweenTest(unittest.TestCase):
    def setUp(self):
        self.end = datetime(2026, 8, 18, 6, 30, tzinfo=UTC)   # 화 15:30 KST
        self.start = self.end - timedelta(hours=24)

    def test_daily_weekday_cron_fires_in_window(self):
        self.assertTrue(cron.fires_between("25 0 * * 2-6", self.start, self.end))

    def test_monday_only_cron_does_not_fire_in_a_tuesday_window(self):
        # 월요일 00:25 UTC는 구간 시작(월 06:30)보다 앞이다.
        self.assertFalse(cron.fires_between("25 0 * * 1", self.start, self.end))

    def test_monthly_cron_does_not_fire_mid_month(self):
        self.assertFalse(cron.fires_between("20 0 1 * *", self.start, self.end))

    def test_previous_evening_cron_is_inside_the_window(self):
        """market_daily는 전날 23:30 UTC다 — 구간을 24시간으로 잡아야 잡힌다."""
        self.assertTrue(cron.fires_between("30 23 * * 1-5", self.start, self.end))


if __name__ == "__main__":
    unittest.main()
