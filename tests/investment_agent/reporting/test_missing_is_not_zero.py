"""결측을 0으로 접지 않는다(RP-03): 부채·D&A가 없으면 순부채·EBITDA는 모른다."""
from __future__ import annotations

import unittest

from investment_agent.reporting.notifications import earnings_report as er
from investment_agent.reporting.services.financial_row import cash_and_equivalents, net_debt, total_debt


class MissingIsNotZeroTest(unittest.TestCase):
    def test_total_debt_without_any_component_is_unknown(self) -> None:
        self.assertIsNone(total_debt({}))
        self.assertIsNone(total_debt({"short_term_debt": None}))

    def test_total_debt_sums_only_known_components(self) -> None:
        self.assertEqual(total_debt({"long_term_debt": 5, "short_term_debt": 2}), 7.0)
        # 보고 총계는 구성요소 합의 검증용일 뿐 총차입 정의에 쓰지 않는다.
        self.assertEqual(total_debt({"total_debt_including_current": 9, "long_term_debt": 1}), 1.0)
        self.assertIsNone(total_debt({"total_debt_including_current": 9}))

    def test_net_debt_is_unknown_when_debt_is_unknown(self) -> None:
        self.assertIsNone(net_debt({"cash_and_cash_equivalents": 100}))

    def test_net_debt_counts_short_term_investments_as_cash(self) -> None:
        """카드(`earnings_report`)와 화면(`services/earnings/metrics`)이 예전에 따로 계산해
        한쪽만 단기투자자산을 반영했다(감사 RR2-08) — 이제 `financial_row.net_debt` 하나다."""
        row = {"long_term_debt": 1000, "cash_and_cash_equivalents": 300, "short_term_investments": 300}
        self.assertEqual(cash_and_equivalents(row), 600.0)
        self.assertEqual(net_debt(row), 400.0)
        # 카드가 직접 부르는 EV 가산분도 같은 정의를 쓴다.
        self.assertEqual(er._ev_ex_market_cap(row), 400.0)

    def test_ebitda_needs_depreciation(self) -> None:
        # 리더가 넘기는 분기 행은 항상 period_end를 갖고, TTM은 이어진 4분기여야 한다.
        ends = ("2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31")
        rows = [{"period_end": end, "operating_income_loss": 10, "depreciation_amortization_cf": None} for end in ends]
        self.assertIsNone(er._ebitda_ttm(rows))
        rows = [{"period_end": end, "operating_income_loss": 10, "depreciation_amortization_cf": 2} for end in ends]
        self.assertEqual(er._ebitda_ttm(rows), 48.0)


if __name__ == "__main__":
    unittest.main()
