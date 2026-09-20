"""매출 컬럼은 총계 태그를 하위 매출 태그보다 먼저 고르고, 크기가 어긋나면 드러낸다.

SEC 원천과 대조한 실측 결함(2026-09):
  - ESS 2025-Q2 총매출 `Revenues` 469.8M인데 ASC 606 하위분 2.2M이 저장됐다.
  - MET 2025-Q2 총매출 17,340M인데 606 하위분 604M이 저장됐다.
  - ADM은 Q1·Q2가 총계, Q3·FY가 606 하위분이라 기간마다 태그가 달라 Q4 파생이 -25.7B가 됐다.
  - DLTR·DD·WDC는 FY만 스핀오프로 재작성돼 분기 합보다 작아 Q4 파생이 음수가 됐다.
"""
from __future__ import annotations

import unittest

from investment_agent.data.fundamentals.domain.services import reported_observations as wide
from investment_agent.data.fundamentals.domain.services.validate_financial_statements import (
    check_core_wide,
)
from investment_agent.data.fundamentals.domain.taxonomy import gaap_concepts as concepts

TOTAL_REVENUE = "Revenues"
BANK_TOTAL_REVENUE = "RevenuesNetOfInterestExpense"
CONTRACT_REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"


def _fact(
    concept: str,
    column_key: str,
    value: float,
    *,
    fiscal_period: str = "Q1",
    qtrs: int = 1,
    period_start: str | None = "2026-01-01",
    period_end: str = "2026-03-31",
    accession_no: str = "ACC-1",
) -> dict:
    return {
        "cik": "0000000001",
        "concept": concept,
        "standard_tag": concepts.to_standard_tag(concept),
        "column_key": column_key,
        "fiscal_year": 2026,
        "fiscal_period": fiscal_period,
        "qtrs": qtrs,
        "form_type": "10-Q",
        "period_start": period_start,
        "period_end": period_end,
        "value": value,
        "unit": "USD",
        "filed_at": "2026-04-30",
        "accession_no": accession_no,
        "is_derived": False,
    }


def _year_of_revenue(q1: float, h1: float, m9: float, fy: float, tag: str = TOTAL_REVENUE) -> list[dict]:
    """Q1·상반기·9개월 누계·FY 매출 fact 네 개."""
    return [
        _fact(tag, "revenue", q1, fiscal_period="Q1", accession_no="Q1"),
        _fact(tag, "revenue", h1, fiscal_period="Q2", qtrs=2, period_end="2026-06-30", accession_no="Q2"),
        _fact(tag, "revenue", m9, fiscal_period="Q3", qtrs=3, period_end="2026-09-30", accession_no="Q3"),
        _fact(tag, "revenue", fy, fiscal_period="FY", qtrs=4, period_end="2026-12-31", accession_no="FY"),
    ]


class RevenueConceptOrderTest(unittest.TestCase):
    def test_total_revenue_tags_outrank_the_customer_contract_subset(self):
        """606 매출은 총매출의 부분집합이라, 총계 태그가 같은 공시에 있으면 그것이 이긴다."""
        contract = concepts.policy_priority(CONTRACT_REVENUE, "revenue")
        self.assertLess(concepts.policy_priority(TOTAL_REVENUE, "revenue"), contract)
        self.assertLess(concepts.policy_priority(BANK_TOTAL_REVENUE, "revenue"), contract)

    def test_the_subset_is_still_used_when_it_is_all_the_filing_reports(self):
        """총계 태그가 없는 정상 기업(다수)은 그대로 606 매출을 쓴다."""
        selected, anomalies = wide.select_semantic_candidates([
            _fact(CONTRACT_REVENUE, "revenue", 1000),
        ])
        self.assertEqual(anomalies, [])
        self.assertEqual([row["value"] for row in selected], [1000])

    def test_a_reit_keeps_total_revenue_not_the_small_contract_line(self):
        """ESS: Revenues 469.8M, 606 하위분 2.2M — 하위분이 저장되던 결함."""
        selected, anomalies = wide.select_semantic_candidates([
            _fact(CONTRACT_REVENUE, "revenue", 2_223_000),
            _fact(TOTAL_REVENUE, "revenue", 469_833_000),
        ])
        self.assertEqual(anomalies, [])
        self.assertEqual(selected[0]["concept"], TOTAL_REVENUE)
        self.assertEqual(selected[0]["value"], 469_833_000)

    def test_a_bank_keeps_net_revenue_not_the_noninterest_contract_line(self):
        """IBKR: RevenuesNetOfInterestExpense 1,896M, 606 하위분 760M."""
        selected, _ = wide.select_semantic_candidates([
            _fact(CONTRACT_REVENUE, "revenue", 760),
            _fact(BANK_TOTAL_REVENUE, "revenue", 1896),
        ])
        self.assertEqual(selected[0]["concept"], BANK_TOTAL_REVENUE)


class FourthQuarterDerivationTest(unittest.TestCase):
    def _q4(self, facts: list[dict]) -> dict | None:
        core, _ = wide.to_wide_tables(facts)
        return next((row for row in core if row["fiscal_period"] == "Q4"), None)

    def test_a_consistent_year_derives_the_fourth_quarter(self):
        q4 = self._q4(_year_of_revenue(100, 210, 330, 460))
        self.assertEqual(q4["revenue"], 130)

    def test_a_fiscal_year_smaller_than_three_quarters_is_not_derived(self):
        """DLTR: FY만 재작성돼 분기 합(22.5B)보다 작다. 음수 매출을 저장하지 않는다."""
        q4 = self._q4(_year_of_revenue(100, 210, 330, 300))
        self.assertTrue(q4 is None or q4.get("revenue") is None, q4)

    def test_outflow_columns_are_not_derived_negative_either(self):
        """capex·자사주·배당 지급은 유출액이라 음수 Q4가 나올 수 없다."""
        facts = [
            _fact("PaymentsToAcquirePropertyPlantAndEquipment", "capital_expenses", value,
                  fiscal_period=fp, qtrs=qtrs, period_end=end, accession_no=fp)
            for fp, qtrs, end, value in (
                ("Q1", 1, "2026-03-31", 30), ("Q2", 2, "2026-06-30", 60),
                ("Q3", 3, "2026-09-30", 100), ("FY", 4, "2026-12-31", 90),
            )
        ]
        q4 = self._q4(facts)
        self.assertTrue(q4 is None or q4.get("capital_expenses") is None, q4)

    def test_a_loss_quarter_is_still_derived_because_income_may_be_negative(self):
        facts = [
            _fact("NetIncomeLoss", "net_income", value, fiscal_period=fp, qtrs=qtrs,
                  period_end=end, accession_no=fp)
            for fp, qtrs, end, value in (
                ("Q1", 1, "2026-03-31", 50), ("Q2", 2, "2026-06-30", 100),
                ("Q3", 3, "2026-09-30", 150), ("FY", 4, "2026-12-31", 100),
            )
        ]
        q4 = self._q4(facts)
        self.assertEqual(q4["net_income"], -50)


class RevenueMagnitudeValidationTest(unittest.TestCase):
    def _row(self, **values) -> dict:
        return {"cik": "0000000001", "fiscal_year": 2026, "fiscal_period": "Q2",
                "filed_at": "2026-08-01", **values}

    def _check(self, **values) -> tuple[dict, list[dict]]:
        clean, anomalies = check_core_wide([self._row(**values)])
        return clean[0], anomalies

    def test_revenue_below_gross_profit_is_cleared_and_reported(self):
        """총이익은 매출보다 클 수 없다 — 매출이 하위 항목이라는 신호."""
        row, anomalies = self._check(revenue=2_223_000, gross_profit=332_181_000)
        self.assertIsNone(row["revenue"])
        self.assertEqual([a["reason"] for a in anomalies], ["revenue_below_profit"])
        self.assertEqual(anomalies[0]["detail"]["revenue"], 2_223_000)

    def test_revenue_below_operating_income_is_cleared_and_reported(self):
        row, anomalies = self._check(revenue=377_000_000, operating_income_loss=900_000_000)
        self.assertIsNone(row["revenue"])
        self.assertEqual([a["reason"] for a in anomalies], ["revenue_below_profit"])

    def test_the_other_profit_columns_are_left_alone(self):
        row, _ = self._check(revenue=2_223_000, gross_profit=332_181_000, net_income=90_000_000)
        self.assertEqual(row["gross_profit"], 332_181_000)
        self.assertEqual(row["net_income"], 90_000_000)

    def test_a_healthy_row_is_untouched(self):
        row, anomalies = self._check(revenue=1000, gross_profit=400, operating_income_loss=100, net_income=80)
        self.assertEqual(row["revenue"], 1000)
        self.assertEqual(anomalies, [])

    def test_net_income_above_revenue_is_legitimate_and_kept(self):
        """자산운용사·매각이익이 있는 기업은 순이익이 매출보다 클 수 있다(KKR·EMR)."""
        row, anomalies = self._check(revenue=372_548_000, net_income=4_420_085_000)
        self.assertEqual(row["revenue"], 372_548_000)
        self.assertEqual(anomalies, [])

    def test_rounding_noise_is_not_an_anomaly(self):
        row, anomalies = self._check(revenue=1000, gross_profit=1000.4)
        self.assertEqual(row["revenue"], 1000)
        self.assertEqual(anomalies, [])


if __name__ == "__main__":
    unittest.main()
