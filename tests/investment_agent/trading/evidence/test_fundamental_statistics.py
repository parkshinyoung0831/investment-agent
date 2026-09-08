"""수정 공시·누락 연도를 전년 성장률로 오인하지 않는다."""
from __future__ import annotations

import unittest

from investment_agent.trading.evidence.tools import fundamental_statistics
from investment_agent.trading.decision import candidate_ranker


class FundamentalStatisticsTest(unittest.TestCase):
    def test_amendment_is_not_a_previous_year(self):
        rows = [
            {"fiscal_year": 2026, "fiscal_period": "Q2", "revenue": 120},
            {"fiscal_year": 2026, "fiscal_period": "Q2", "revenue": 110},
            {"fiscal_year": 2025, "fiscal_period": "Q2", "revenue": 100},
        ]
        self.assertAlmostEqual(0.2, fundamental_statistics(rows)["revenue_growth_yoy"])
        self.assertIs(fundamental_statistics, candidate_ranker.fundamental_statistics)

    def test_missing_prior_year_is_not_a_two_year_growth(self):
        rows = [
            {"fiscal_year": 2026, "fiscal_period": "FY", "revenue": 120},
            {"fiscal_year": 2024, "fiscal_period": "FY", "revenue": 100},
        ]
        self.assertNotIn("revenue_growth_yoy", fundamental_statistics(rows))

    def test_missing_year_does_not_invent_comparability(self):
        rows = [{"fiscal_period": "Q1", "revenue": 120}, {"fiscal_period": "Q1", "revenue": 100}]
        self.assertNotIn("revenue_growth_yoy", fundamental_statistics(rows))
