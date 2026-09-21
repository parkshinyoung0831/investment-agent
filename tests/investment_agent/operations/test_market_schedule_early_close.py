"""NYSE 정규 조기 마감(13:00 ET)일을 알고, 그 날 판단·감시 창이 폐장 뒤로 열려 있지 않다(OP-01).

아래 날짜는 NYSE 공식 조기 마감 일정이다.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone

from investment_agent.operations.harness.market_schedule import (
    NY_TZ, SessionWindow, USMarketPhase, get_us_market_phase, is_early_close_day, us_market_close_time,
)

NYSE_EARLY_CLOSES = {
    2024: [(7, 3), (11, 29), (12, 24)],
    2025: [(7, 3), (11, 28), (12, 24)],
    2026: [(11, 27), (12, 24)],          # 7/3은 독립기념일 대체 휴장이라 조기 마감이 아니다
    2027: [(11, 26)],                    # 12/24는 크리스마스 대체 휴장
}


def _found(year: int) -> set[tuple[int, int]]:
    out, day = set(), date(year, 1, 1)
    while day.year == year:
        if is_early_close_day(day):
            out.add((day.month, day.day))
        day += timedelta(days=1)
    return out


def _utc(day: date, wall: time) -> datetime:
    return datetime.combine(day, wall, tzinfo=NY_TZ).astimezone(timezone.utc)


class EarlyCloseRulesTest(unittest.TestCase):
    def test_every_day_of_each_year_matches_the_official_schedule(self) -> None:
        for year, expected in NYSE_EARLY_CLOSES.items():
            with self.subTest(year=year):
                self.assertEqual(_found(year), set(expected))

    def test_close_time_is_13_on_early_days_16_on_normal_days_and_none_on_holidays(self) -> None:
        self.assertEqual(us_market_close_time(date(2025, 11, 28)), time(13, 0))
        self.assertEqual(us_market_close_time(date(2025, 11, 26)), time(16, 0))
        self.assertIsNone(us_market_close_time(date(2025, 11, 27)))   # 추수감사절
        self.assertIsNone(us_market_close_time(date(2025, 11, 29)))   # 토요일


class SessionWindowOnEarlyCloseTest(unittest.TestCase):
    def test_the_judgement_window_keeps_its_distance_from_the_close(self) -> None:
        day = date(2025, 11, 28)  # 13:00 폐장 → 판단 창(마감 90분 전)은 11:30까지
        window = SessionWindow()  # 09:40~14:30
        self.assertTrue(window.is_open(_utc(day, time(11, 29))))
        self.assertFalse(window.is_open(_utc(day, time(12, 0))))
        self.assertFalse(window.is_open(_utc(day, time(13, 30))))     # 예전에는 14:30까지 열려 있었다
        normal = date(2025, 11, 26)
        self.assertTrue(window.is_open(_utc(normal, time(13, 30))))

    def test_the_risk_window_still_covers_thirty_minutes_after_the_close(self) -> None:
        risk = SessionWindow(start=time(9, 15), end=time(16, 30))
        early, normal = date(2025, 11, 28), date(2025, 11, 26)
        self.assertTrue(risk.is_open(_utc(early, time(13, 20))))       # 마감 13:00 + 30분 안
        self.assertFalse(risk.is_open(_utc(early, time(13, 40))))
        self.assertTrue(risk.is_open(_utc(normal, time(16, 20))))      # 정상일은 그대로 16:30까지

    def test_phase_switches_to_post_close_at_13(self) -> None:
        day = date(2025, 11, 28)
        self.assertEqual(get_us_market_phase(_utc(day, time(12, 30))).phase, USMarketPhase.REGULAR_TRADING)
        self.assertEqual(get_us_market_phase(_utc(day, time(13, 30))).phase, USMarketPhase.POST_CLOSE_ANALYSIS)
        self.assertEqual(get_us_market_phase(_utc(date(2025, 11, 26), time(13, 30))).phase,
                         USMarketPhase.REGULAR_TRADING)


if __name__ == "__main__":
    unittest.main()
