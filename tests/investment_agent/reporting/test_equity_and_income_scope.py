"""영업현금흐름·부채와 맞대는 계산은 같은 범위(연결·자본 총계)의 값을 쓴다."""
from __future__ import annotations

import unittest

from investment_agent.notifications.earnings_report.charts import _bridge_parts
from investment_agent.reporting.notifications.earnings_report import _altman_z
from investment_agent.reporting.services.financial_row import (
    consolidated_net_income,
    total_book_equity,
)
from investment_agent.research.evidence.statistics import quality_statistics


class ScopeTest(unittest.TestCase):
    def test_consolidated_income_adds_the_nci_share(self) -> None:
        self.assertEqual(110.0, consolidated_net_income({"net_income": 100, "minority_interest_income": 10}))
        self.assertIsNone(consolidated_net_income({"minority_interest_income": 10}))

    def test_book_equity_is_every_permanent_equity_claim(self) -> None:
        row = {"common_equity": 100, "preferred_stock": 5, "minority_interest_balance": 20}
        self.assertEqual(125.0, total_book_equity(row))

    def test_cash_bridge_starts_from_consolidated_income(self) -> None:
        parts = _bridge_parts({"net_income": 100.0, "minority_interest_income": 10.0,
                               "net_cash_from_operating_activities": 130.0})
        self.assertEqual(110.0, parts["순이익"])
        self.assertEqual(20.0, parts["±운전자본/기타"])

    def test_altman_equity_term_uses_total_book_equity(self) -> None:
        row = {"assets": 1000.0, "liabilities": 500.0, "current_assets_total": 300.0,
               "current_liabilities_total": 200.0, "retained_earnings": 100.0,
               "common_equity": 300.0, "preferred_stock": 50.0, "minority_interest_balance": 150.0}
        without_claims = {**row, "preferred_stock": None, "minority_interest_balance": None}
        difference = _altman_z(row, operating_ttm=50.0) - _altman_z(without_claims, operating_ttm=50.0)
        self.assertAlmostEqual(1.05 * 200.0 / 500.0, difference)

    def test_accruals_use_consolidated_income(self) -> None:
        rows = [
            {"fiscal_year": 2025, "fiscal_period": f"Q{q}", "period_end": end, "revenue": 100.0,
             "net_income": 10.0, "minority_interest_income": 2.0,
             "net_cash_from_operating_activities": 12.0, "assets": 400.0}
            for q, end in ((4, "2025-12-31"), (3, "2025-09-30"), (2, "2025-06-30"), (1, "2025-03-31"))
        ]
        self.assertAlmostEqual(0.0, quality_statistics(rows)["accruals_ttm"])


if __name__ == "__main__":
    unittest.main()
