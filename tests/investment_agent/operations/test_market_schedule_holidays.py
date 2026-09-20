"""하네스의 NYSE 휴장일 규칙이 공식 휴장일과 일 단위로 일치하는지 연도 전수로 대조한다.

실측 결함(2026-09): 표에 Good Friday가 없어 2026-04-03을 열린 날로 봤고, 1월 1일이 토요일인 해의
직전 금요일(2027-12-31)은 NYSE가 여는데 휴장으로 봤다. 판정은 `SessionWindow`·시장 국면·판단 시작 창을
결정한다. 아래 목록은 NYSE 공식 휴장 일정이다. 1회성 임시 휴장(예: 2025-01-09 카터 추모일)은 규칙으로
나올 수 없어 목록에서 뺀다 — 실주문은 브로커 캘린더가 따로 거른다.
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.operations.harness.market_schedule import is_us_market_holiday

NYSE_SCHEDULED_HOLIDAYS = {
    2024: [(1, 1), (1, 15), (2, 19), (3, 29), (5, 27), (6, 19), (7, 4), (9, 2), (11, 28), (12, 25)],
    2025: [(1, 1), (1, 20), (2, 17), (4, 18), (5, 26), (6, 19), (7, 4), (9, 1), (11, 27), (12, 25)],
    2026: [(1, 1), (1, 19), (2, 16), (4, 3), (5, 25), (6, 19), (7, 3), (9, 7), (11, 26), (12, 25)],
    # 6/19가 토요일이라 6/18, 7/4가 일요일이라 7/5, 12/25가 토요일이라 12/24에 쉰다.
    2027: [(1, 1), (1, 18), (2, 15), (3, 26), (5, 31), (6, 18), (7, 5), (9, 6), (11, 25), (12, 24)],
    # 1월 1일이 토요일: 직전 금요일(2027-12-31)에도, 다음 월요일에도 쉬지 않는다.
    2028: [(1, 17), (2, 21), (4, 14), (5, 29), (6, 19), (7, 4), (9, 4), (11, 23), (12, 25)],
}


def _holidays_found(year: int) -> set[tuple[int, int]]:
    found = set()
    day = date(year, 1, 1)
    while day.year == year:
        if is_us_market_holiday(day):
            found.add((day.month, day.day))
        day += timedelta(days=1)
    return found


class UsMarketHolidayRulesTest(unittest.TestCase):
    def test_every_day_of_each_year_matches_the_official_schedule(self):
        for year, expected in NYSE_SCHEDULED_HOLIDAYS.items():
            with self.subTest(year=year):
                found = _holidays_found(year)
                self.assertEqual(sorted(found - set(expected)), [], f"{year}: 열린 날을 휴장으로 봄")
                self.assertEqual(sorted(set(expected) - found), [], f"{year}: 휴장일을 열린 날로 봄")

    def test_good_friday_is_a_holiday(self):
        for good_friday in (date(2025, 4, 18), date(2026, 4, 3), date(2027, 3, 26)):
            self.assertTrue(is_us_market_holiday(good_friday), good_friday)

    def test_the_friday_before_a_saturday_new_year_stays_open(self):
        """NYSE는 1월 1일이 토요일이면 직전 금요일에 연다(다른 토요일 공휴일과 다른 유일한 예외)."""
        self.assertFalse(is_us_market_holiday(date(2027, 12, 31)))

    def test_weekends_that_are_not_observed_holidays_stay_false(self):
        """규칙은 평일만 휴장으로 본다 — 주말 판정은 호출부의 weekday 검사가 맡는다."""
        self.assertFalse(is_us_market_holiday(date(2026, 7, 4)))   # 토요일, 7/3에 쉼
        self.assertFalse(is_us_market_holiday(date(2027, 12, 25)))  # 토요일, 12/24에 쉼


if __name__ == "__main__":
    unittest.main()
