"""컬럼마다 한 가지 회계 개념만 담긴다 — 부분 항목·다른 범위·뺄셈 파생을 막는 규칙."""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.data.fundamentals.domain.normalization import build_company_financials
from investment_agent.data.fundamentals.domain.services.reported_observations import to_wide_tables
from investment_agent.data.fundamentals.domain.services.validate_financial_statements import (
    check_core_wide,
)
from investment_agent.data.fundamentals.domain.taxonomy import gaap_concepts as concepts

CIK = "0000000001"


def _fact(concept: str, value: float, *, fp: str = "Q1", qtrs: int = 1,
          start: str | None = "2026-01-01", end: str = "2026-03-31", fy: int = 2026,
          unit: str = "USD") -> dict:
    return {
        "cik": CIK, "statement": "IS", "concept": concept, "standard_tag": concept,
        "column_key": concepts.to_column_key(concept), "fiscal_year": fy, "fiscal_period": fp,
        "qtrs": qtrs, "form_type": "10-Q", "period_start": start, "period_end": end,
        "value": value, "unit": unit, "filed_at": "2026-05-01", "accession_no": f"ACC-{fp}",
        "is_derived": False,
    }


class PolicyRoutingTest(unittest.TestCase):
    def test_every_policy_tag_reaches_its_column(self) -> None:
        for column, policy in concepts.COLUMN_POLICIES.items():
            for tag in policy.priority:
                with self.subTest(tag=tag):
                    self.assertEqual(column, concepts.to_column_key(tag))

    def test_a_tag_in_two_policies_is_refused(self) -> None:
        duplicated = {
            **concepts.COLUMN_POLICIES,
            "short_term_debt": concepts.ColumnPolicy({"LongTermDebtCurrent": 10}),
        }
        with mock.patch.object(concepts, "COLUMN_POLICIES", duplicated):
            with self.assertRaises(ValueError):
                concepts._policy_routes()

    def test_components_and_overlapping_totals_are_not_accepted(self) -> None:
        refused = {
            ("DebtCurrent", "short_term_debt"),              # 유동성 장기부채 포함
            ("LongTermDebt", "long_term_debt"),               # 유동분 포함
            ("SalesAndMarketingExpense", "operating_income_loss"),
            ("InterestAndDividendIncomeOperating", "net_interest_income"),  # 이자수익 총액
            ("OperatingLeaseLiability", "operating_lease_current_debt_equivalent"),
            ("InventoryRawMaterials", "inventories"),
            ("ProfitLoss", "net_income"),                     # 비지배지분 포함
        }
        for tag, column in refused:
            with self.subTest(tag=tag):
                self.assertFalse(concepts.policy_accepts(tag, column, "USD"))


class NetIncomeScopeTest(unittest.TestCase):
    def test_parent_net_income_is_derived_from_consolidated_minus_nci(self) -> None:
        rows, _ = to_wide_tables([
            _fact("ProfitLoss", 100),
            _fact("NetIncomeLossAttributableToNoncontrollingInterest", 10),
        ])
        self.assertEqual(90, rows[0]["net_income"])
        self.assertNotIn("net_income_including_nci", rows[0])

    def test_reported_parent_net_income_wins(self) -> None:
        rows, _ = to_wide_tables([
            _fact("ProfitLoss", 100),
            _fact("NetIncomeLoss", 88),
            _fact("NetIncomeLossAttributableToNoncontrollingInterest", 10),
        ])
        self.assertEqual(88, rows[0]["net_income"])

    def test_consolidated_income_without_nci_is_not_used(self) -> None:
        rows, _ = to_wide_tables([_fact("ProfitLoss", 100), _fact("Revenues", 500)])
        self.assertIsNone(rows[0]["net_income"])


class PerShareTest(unittest.TestCase):
    def test_q4_eps_is_income_over_shares_not_fy_minus_quarters(self) -> None:
        facts = []
        for fp, start, end in (("Q1", "2025-01-01", "2025-03-31"), ("Q2", "2025-04-01", "2025-06-30"),
                               ("Q3", "2025-07-01", "2025-09-30")):
            facts += [
                _fact("NetIncomeLoss", 100, fp=fp, start=start, end=end, fy=2025),
                _fact("EarningsPerShareDiluted", 1.0, fp=fp, start=start, end=end, fy=2025,
                      unit="USD/shares"),
                _fact("WeightedAverageNumberOfDilutedSharesOutstanding", 100, fp=fp, start=start,
                      end=end, fy=2025, unit="shares"),
            ]
        facts += [
            _fact("NetIncomeLoss", 400, fp="FY", qtrs=4, start="2025-01-01", end="2025-12-31", fy=2025),
            # 보고 FY EPS는 반올림돼 3.9 — 빼면 Q4가 0.9로 나온다.
            _fact("EarningsPerShareDiluted", 3.9, fp="FY", qtrs=4, start="2025-01-01",
                  end="2025-12-31", fy=2025, unit="USD/shares"),
            _fact("WeightedAverageNumberOfDilutedSharesOutstanding", 100, fp="FY", qtrs=4,
                  start="2025-01-01", end="2025-12-31", fy=2025, unit="shares"),
        ]

        rows = build_company_financials(facts).core_rows
        q4 = next(row for row in rows if row["fiscal_period"] == "Q4")

        self.assertAlmostEqual(1.0, q4["eps_diluted_gaap"])
        self.assertEqual(
            "net_income / shares_fully_diluted_average",
            q4["source_manifest"]["eps_diluted_gaap"]["derivation"]["formula"],
        )


    def test_eps_is_not_made_from_a_share_count_off_by_a_unit(self) -> None:
        """자기 입력으로 만든 EPS는 주식수 단위 검사를 늘 통과한다 — 다른 분기와 자릿수가 다르면 만들지 않는다."""
        rows = [
            {"cik": CIK, "fiscal_year": 2025, "fiscal_period": fp, "period_end": end,
             "net_income": 100.0, "shares_fully_diluted_average": shares, "eps_diluted_gaap": eps}
            for fp, end, shares, eps in (
                ("Q1", "2025-03-31", 100.0, 1.0), ("Q2", "2025-06-30", 100.0, 1.0),
                ("Q3", "2025-09-30", 100.0, 1.0), ("Q4", "2025-12-31", 100_000.0, None),
            )
        ]
        clean, _ = check_core_wide(rows)
        self.assertIsNone(clean[-1]["eps_diluted_gaap"])


class ValidationRulesTest(unittest.TestCase):
    def _row(self, **values) -> dict:
        return {"cik": CIK, "fiscal_year": 2026, "fiscal_period": "Q1",
                "period_end": "2026-03-31", **values}

    def test_revenue_far_below_assets_is_withheld(self) -> None:
        clean, anomalies = check_core_wide([self._row(revenue=3e6, assets=9.4e9)])
        self.assertIsNone(clean[0]["revenue"])
        self.assertEqual("revenue_below_asset_floor", anomalies[0]["reason"])

    def test_a_bank_scale_revenue_is_kept(self) -> None:
        clean, anomalies = check_core_wide([self._row(revenue=2.0e9, assets=250e9)])
        self.assertEqual(2.0e9, clean[0]["revenue"])
        self.assertEqual([], anomalies)

    def test_negative_capex_is_withheld(self) -> None:
        clean, anomalies = check_core_wide([self._row(capital_expenses=-5.0, revenue=100.0)])
        self.assertIsNone(clean[0]["capital_expenses"])
        self.assertEqual("negative_nonnegative_flow", anomalies[0]["reason"])


if __name__ == "__main__":
    unittest.main()
