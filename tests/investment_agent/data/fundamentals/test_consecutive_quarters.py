"""TTM은 빠짐없이 이어진 4분기여야 한다 — 중간 분기가 비면 5분기에 걸친 합이 TTM으로 나간다.

실측: `fundamentals.financials` 인접 `period_end` 간격 15,800쌍 중 84~98일(52/53주 결산사의 12~14주 분기)이
99.6%이고, 나머지는 분기가 빠졌거나(182~185일, 454일 이상) 회계연도가 바뀐 구간이다. 세 곳(카드 TTM·research
valuation·research quality)이 각자 최근 4행을 자르기만 해서 그런 행을 그대로 합산했다.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from investment_agent.data.fundamentals.domain.periods import are_consecutive_quarters
from investment_agent.reporting.notifications import earnings_report
from investment_agent.research.evidence.statistics import quality_statistics
from investment_agent.research.valuation.inputs import ttm_scalars

CONTIGUOUS = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]
MISSING_ONE = ["2025-03-31", "2025-09-30", "2025-12-31", "2026-03-31"]  # 2025-06-30이 빠짐


def _rows(period_ends: list[str], **fields) -> list[dict]:
    fiscal = [("Q2", 2025), ("Q3", 2025), ("Q4", 2025), ("Q1", 2026)]
    rows = []
    for index, period_end in enumerate(period_ends):
        period, year = fiscal[index]
        rows.append({
            "ticker": "T", "period_end": period_end, "fiscal_year": year, "fiscal_period": period,
            "filed_at": (date.fromisoformat(period_end) + timedelta(days=30)).isoformat(), "revenue": 100.0, "net_income": 10.0,
            "operating_income_loss": 15.0, "gross_profit": 40.0, "net_cash_from_operating_activities": 12.0,
            "capital_expenses": 3.0, "interest_expense": 1.0, "common_equity": 200.0, "assets": 500.0,
            "liabilities": 300.0, "accession_no": f"A-{index}", **fields,
        })
    return rows


class ConsecutiveQuartersTest(unittest.TestCase):
    def test_contiguous_calendar_quarters(self):
        self.assertTrue(are_consecutive_quarters(CONTIGUOUS))

    def test_a_missing_quarter_is_not_consecutive(self):
        self.assertFalse(are_consecutive_quarters(MISSING_ONE))

    def test_fifty_two_and_fifty_three_week_quarters_are_consecutive(self):
        """12주(84일)와 14주(98일) 분기가 섞여도 연속이다."""
        self.assertTrue(are_consecutive_quarters(["2025-04-05", "2025-07-05", "2025-10-04", "2026-01-03"]))
        self.assertTrue(are_consecutive_quarters([date(2025, 3, 1), date(2025, 5, 24), date(2025, 8, 30)]))

    def test_the_order_of_the_input_does_not_matter(self):
        self.assertTrue(are_consecutive_quarters(list(reversed(CONTIGUOUS))))

    def test_overlapping_period_ends_are_not_consecutive(self):
        self.assertFalse(are_consecutive_quarters(["2025-06-30", "2025-07-15", "2025-09-30"]))

    def test_fewer_than_two_period_ends_have_nothing_missing(self):
        self.assertTrue(are_consecutive_quarters([]))
        self.assertTrue(are_consecutive_quarters(["2025-06-30"]))


class CardTtmTest(unittest.TestCase):
    def test_contiguous_window_sums(self):
        self.assertEqual(earnings_report._ttm(_rows(CONTIGUOUS), "revenue"), 400.0)

    def test_window_with_a_missing_quarter_is_not_a_ttm(self):
        self.assertIsNone(earnings_report._ttm(_rows(MISSING_ONE), "revenue"))


class ResearchTtmTest(unittest.TestCase):
    AS_OF = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def test_valuation_ttm_from_contiguous_quarters(self):
        scalars = ttm_scalars(_rows(CONTIGUOUS), as_of_at=self.AS_OF)
        self.assertEqual(float(scalars["revenue_ttm"].value), 400.0)

    def test_valuation_ttm_is_missing_with_a_named_reason_when_a_quarter_is_missing(self):
        scalars = ttm_scalars(_rows(MISSING_ONE), as_of_at=self.AS_OF)
        self.assertIsNone(scalars["revenue_ttm"].value)
        self.assertEqual(scalars["revenue_ttm"].missing_reason, "ttm_quarters_not_consecutive")

    def test_quality_statistics_need_contiguous_quarters(self):
        self.assertTrue(quality_statistics(_rows(CONTIGUOUS)))
        self.assertEqual(quality_statistics(_rows(MISSING_ONE)), {})


if __name__ == "__main__":
    unittest.main()
