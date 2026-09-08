"""회계기간을 추측하지 않고, 부분합으로 Q4를 만들지 않는다."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.fundamentals.domain.periods import (
    FiscalPeriod,
    PeriodError,
    derive_fourth_quarter,
    parse_period,
    period_end_is_plausible,
    sorted_periods,
    trailing_quarters,
)


class FiscalPeriodTest(unittest.TestCase):
    def test_unknown_period_is_refused(self) -> None:
        with self.assertRaises(PeriodError):
            FiscalPeriod(2026, "H1")

    def test_year_out_of_range_is_refused(self) -> None:
        with self.assertRaises(PeriodError):
            FiscalPeriod(26, "Q1")

    def test_previous_quarter_crosses_the_year(self) -> None:
        self.assertEqual(FiscalPeriod(2025, "Q4"), FiscalPeriod(2026, "Q1").previous_quarter())

    def test_annual_has_no_previous_quarter(self) -> None:
        """FY의 '직전'은 분기가 아니다. 임의로 정하면 추세가 조용히 어긋난다."""
        with self.assertRaises(PeriodError):
            FiscalPeriod(2026, "FY").previous_quarter()

    def test_year_ago_keeps_the_quarter(self) -> None:
        """계절성이 큰 사업에서 전분기 대비는 의미가 없다."""
        self.assertEqual(FiscalPeriod(2025, "Q3"), FiscalPeriod(2026, "Q3").year_ago())

    def test_periods_sort_in_time_order(self) -> None:
        unordered = [FiscalPeriod(2026, "FY"), FiscalPeriod(2026, "Q1"), FiscalPeriod(2025, "Q4")]
        self.assertEqual(
            [FiscalPeriod(2025, "Q4"), FiscalPeriod(2026, "Q1"), FiscalPeriod(2026, "FY")],
            sorted_periods(unordered),
        )


class ParsePeriodTest(unittest.TestCase):
    def test_known_forms_are_accepted(self) -> None:
        self.assertEqual("Q1", parse_period("q1"))
        self.assertEqual("FY", parse_period(" annual "))

    def test_unknown_form_raises_instead_of_guessing(self) -> None:
        for value in (None, "", "H1", "2026"):
            with self.subTest(value=value), self.assertRaises(PeriodError):
                parse_period(value)


class TrailingQuartersTest(unittest.TestCase):
    def test_thirteen_quarters_walk_back_through_years(self) -> None:
        periods = trailing_quarters(FiscalPeriod(2026, "Q2"), 13)
        self.assertEqual(13, len(periods))
        self.assertEqual(FiscalPeriod(2023, "Q2"), periods[0])
        self.assertEqual(FiscalPeriod(2026, "Q2"), periods[-1])

    def test_annual_input_is_refused(self) -> None:
        with self.assertRaises(PeriodError):
            trailing_quarters(FiscalPeriod(2026, "FY"), 4)

    def test_zero_count_is_refused(self) -> None:
        with self.assertRaises(PeriodError):
            trailing_quarters(FiscalPeriod(2026, "Q2"), 0)


class DeriveFourthQuarterTest(unittest.TestCase):
    def test_annual_minus_three_quarters(self) -> None:
        self.assertAlmostEqual(25.0, derive_fourth_quarter(100.0, [25.0, 25.0, 25.0]))

    def test_a_missing_quarter_gives_none_not_a_partial_sum(self) -> None:
        """부분합으로 빼면 Q4가 실제보다 크게 나오고 그 값이 차트에 그대로 실린다."""
        self.assertIsNone(derive_fourth_quarter(100.0, [25.0, 25.0, None]))

    def test_a_missing_annual_gives_none(self) -> None:
        self.assertIsNone(derive_fourth_quarter(None, [25.0, 25.0, 25.0]))

    def test_wrong_number_of_quarters_gives_none(self) -> None:
        self.assertIsNone(derive_fourth_quarter(100.0, [25.0, 25.0]))


class PlausibilityTest(unittest.TestCase):
    def test_a_period_ending_after_the_filing_is_refused(self) -> None:
        """소스가 연도를 잘못 붙이면 그 행이 PIT 조회에 미래로 새어 든다."""
        self.assertFalse(period_end_is_plausible(date(2027, 3, 31), date(2026, 5, 1)))

    def test_the_normal_order_passes(self) -> None:
        self.assertTrue(period_end_is_plausible(date(2026, 3, 31), date(2026, 5, 1)))


if __name__ == "__main__":
    unittest.main()
