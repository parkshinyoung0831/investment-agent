"""결측을 0으로 접지 않는다(RP-03): 부채·D&A가 없으면 순부채·EBITDA는 모른다."""
from __future__ import annotations

import unittest

from investment_agent.reporting.notifications import earnings_report as er
from investment_agent.reporting.services.financial_row import total_debt


class MissingIsNotZeroTest(unittest.TestCase):
    def test_total_debt_without_any_component_is_unknown(self) -> None:
        self.assertIsNone(total_debt({}))
        self.assertIsNone(total_debt({"short_term_debt": None}))

    def test_total_debt_sums_only_known_components(self) -> None:
        self.assertEqual(total_debt({"long_term_debt": 5, "short_term_debt": 2}), 7.0)
        self.assertEqual(total_debt({"total_debt_including_current": 9, "long_term_debt": 1}), 9.0)

    def test_net_debt_is_unknown_when_debt_is_unknown(self) -> None:
        self.assertIsNone(er._net_debt({"cash_and_cash_equivalents": 100}))

    def test_ebitda_needs_depreciation(self) -> None:
        # 리더가 넘기는 분기 행은 항상 period_end를 갖고, TTM은 이어진 4분기여야 한다.
        ends = ("2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31")
        rows = [{"period_end": end, "operating_income_loss": 10, "depreciation_amortization_cf": None} for end in ends]
        self.assertIsNone(er._ebitda_ttm(rows))
        rows = [{"period_end": end, "operating_income_loss": 10, "depreciation_amortization_cf": 2} for end in ends]
        self.assertEqual(er._ebitda_ttm(rows), 48.0)


if __name__ == "__main__":
    unittest.main()
