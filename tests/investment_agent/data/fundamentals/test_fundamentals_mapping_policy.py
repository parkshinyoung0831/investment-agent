"""컬럼 매핑 정책 — 단위 게이트와 동률 처리.

적재 결과 실측에서, 정책이 없는 컬럼은 동률일 때 태그 이름의 알파벳 순으로
값을 골랐고 그 규칙이 회계적으로 다른 개념을 계통적으로 선택하고 있었다
(이연법인세를 총법인세로, 부채상환손익을 이자비용으로, 자기주식 금액을 주식수로).
아래 테스트는 그 회귀를 막는다.
"""
from __future__ import annotations

import unittest

from investment_agent.data.fundamentals.domain.taxonomy import gaap_concepts as concepts


class PolicyUnitGate(unittest.TestCase):
    def test_wide_columns_without_policy_still_check_units(self):
        """정책이 없는 wide 컬럼도 기대 단위가 아니면 받지 않는다."""
        self.assertTrue(concepts.policy_accepts("Assets", "assets", "USD"))
        self.assertFalse(concepts.policy_accepts("Assets", "assets", "shares"))
        self.assertTrue(
            concepts.policy_accepts(
                "WeightedAverageNumberOfSharesOutstandingBasic",
                "shares_average",
                "shares",
            )
        )

    def test_non_wide_column_is_not_unit_gated(self):
        """wide 컬럼이 아니면 어차피 버려지므로 단위를 따지지 않는다."""
        self.assertTrue(concepts.policy_accepts("SomeTag", "not_a_wide_column", None))


class PolicyConceptChoice(unittest.TestCase):
    def test_balance_sheet_totals_reject_partial_accounts(self):
        self.assertTrue(concepts.policy_accepts("Assets", "assets", "USD"))
        self.assertFalse(
            concepts.policy_accepts(
                "VariableInterestEntityConsolidatedCarryingAmountAssets",
                "assets",
                "USD",
            )
        )
        self.assertTrue(
            concepts.policy_accepts("Liabilities", "liabilities", "USD")
        )
        self.assertFalse(
            concepts.policy_accepts("UnearnedPremiums", "liabilities", "USD")
        )

    def test_income_taxes_takes_total_not_deferred(self):
        self.assertTrue(
            concepts.policy_accepts("IncomeTaxExpenseBenefit", "income_taxes", "USD")
        )
        for rejected in ("DeferredIncomeTaxExpenseBenefit", "IncomeTaxesPaidNet"):
            self.assertFalse(
                concepts.policy_accepts(rejected, "income_taxes", "USD"), rejected
            )

    def test_interest_expense_rejects_unrelated_concepts(self):
        self.assertTrue(
            concepts.policy_accepts("InterestExpense", "interest_expense", "USD")
        )
        for rejected in (
            "GainsLossesOnExtinguishmentOfDebt",
            "InterestPaidNet",
            "AmortizationOfFinancingCostsAndDiscounts",
        ):
            self.assertFalse(
                concepts.policy_accepts(rejected, "interest_expense", "USD"), rejected
            )

    def test_cost_of_sales_prefers_total_over_partial_cost(self):
        priority = concepts.COLUMN_POLICIES["cost_of_goods_and_services_sold"].priority
        self.assertLess(
            priority["CostOfGoodsAndServicesSold"],
            priority["CostOfRevenue"],
        )
        self.assertFalse(
            concepts.policy_accepts(
                "LaborAndRelatedExpense", "cost_of_goods_and_services_sold", "USD"
            )
        )

    def test_depreciation_prefers_widest_concept(self):
        priority = concepts.COLUMN_POLICIES["depreciation_amortization_cf"].priority
        self.assertLess(
            priority["DepreciationDepletionAndAmortization"],
            priority["Depreciation"],
        )

    def test_diluted_shares_accepts_only_weighted_average_denominators(self):
        column = "shares_fully_diluted_average"
        self.assertLess(
            concepts.policy_priority(
                "WeightedAverageNumberOfDilutedSharesOutstanding", column
            ),
            concepts.policy_priority(
                "WeightedAverageNumberOfShareOutstandingBasicAndDiluted", column
            ),
        )
        for tag in (
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
        ):
            self.assertTrue(concepts.policy_accepts(tag, column, "shares"), tag)
        for rejected in (
            "ConversionOfStockSharesConverted1",
            "StockIssuedDuringPeriodSharesConversionOfConvertibleSecurities",
        ):
            self.assertFalse(
                concepts.policy_accepts(rejected, column, "shares"), rejected
            )

    def test_total_deposits_rejects_components_and_fair_value(self):
        self.assertTrue(
            concepts.policy_accepts("Deposits", "total_deposits", "USD")
        )
        for rejected in (
            "InterestBearingDepositLiabilities",
            "NoninterestBearingDepositLiabilities",
            "TimeDeposits",
            "DepositsFairValueDisclosure",
        ):
            self.assertFalse(
                concepts.policy_accepts(rejected, "total_deposits", "USD"),
                rejected,
            )

    def test_minority_interest_rejects_vie_assets_and_liabilities(self):
        column = "minority_interest_balance"
        for tag in (
            "MinorityInterest",
            "NoncontrollingInterests",
            "MinorityInterestInOperatingPartnerships",
            "MinorityInterestInLimitedPartnerships",
        ):
            self.assertTrue(concepts.policy_accepts(tag, column, "USD"), tag)
        for rejected in (
            "VariableInterestEntityConsolidatedCarryingAmountAssets",
            "VariableInterestEntityConsolidatedCarryingAmountLiabilities",
            "NoncontrollingInterestInVariableInterestEntity",
        ):
            self.assertFalse(
                concepts.policy_accepts(rejected, column, "USD"), rejected
            )

    def test_permanent_partnership_interest_is_not_mezzanine_equity(self):
        for tag in (
            "MinorityInterestInOperatingPartnerships",
            "MinorityInterestInLimitedPartnerships",
        ):
            self.assertEqual(
                concepts.to_column_key(tag), "minority_interest_balance", tag
            )
            self.assertFalse(
                concepts.policy_accepts(tag, "mezzanine_equity", "USD"), tag
            )

    def test_spac_trust_assets_are_transformation_only(self):
        self.assertEqual(
            concepts.to_column_key("AssetsHeldInTrust"),
            "assets_held_in_trust",
        )
        self.assertTrue(
            concepts.policy_accepts(
                "AssetsHeldInTrust", "assets_held_in_trust", "USD"
            )
        )

    def test_mezzanine_policy_prefers_reported_totals(self):
        column = "mezzanine_equity"
        for tag in (
            "TemporaryEquityCarryingAmount",
            "RedeemableNoncontrollingInterestEquityCarryingAmount",
            "RedeemableNoncontrollingInterestEquityOtherCarryingAmount",
        ):
            self.assertEqual(concepts.to_column_key(tag), column, tag)
            self.assertTrue(concepts.policy_accepts(tag, column, "USD"), tag)
        self.assertLess(
            concepts.policy_priority("TemporaryEquityCarryingAmount", column),
            concepts.policy_priority(
                "RedeemableNoncontrollingInterestEquityCarryingAmount", column
            ),
        )

    def test_redeemable_nci_fair_value_is_valid_mezzanine(self):
        column = "mezzanine_equity"
        for tag in (
            "RedeemableNoncontrollingInterestEquityFairValue",
            "RedeemableNoncontrollingInterestEquityCommonFairValue",
            "RedeemableNoncontrollingInterestEquityOtherFairValue",
        ):
            self.assertEqual(concepts.to_column_key(tag), column, tag)
            self.assertTrue(concepts.policy_accepts(tag, column, "USD"), tag)


class ConflictRejection(unittest.TestCase):
    def test_columns_without_policy_reject_ties_by_default(self):
        """정책이 없어도 동률이면 임의로 고르지 않고 비워둔다."""
        self.assertTrue(
            concepts.policy_rejects_conflict("stock_repurchase_payments")
        )

    def test_policy_columns_reject_ties(self):
        self.assertTrue(concepts.policy_rejects_conflict("income_taxes"))


class CashFlowConceptChoice(unittest.TestCase):
    """현금흐름표 계열 — 총계 자리에 라인아이템이 들어오지 않는지."""

    def test_dividends_paid_routes_cash_payment_not_declaration(self):
        """배당 '지급액'은 현금흐름표 태그다. 자본변동표의 선언액과 섞이면
        dividend_yield가 선언액 기준이 된다."""
        for tag in ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"):
            self.assertEqual(
                concepts.to_column_key(tag), "common_dividends_paid", tag
            )
            self.assertTrue(
                concepts.policy_accepts(tag, "common_dividends_paid", "USD"), tag
            )
        for declared in ("DividendsCommonStockCash", "DividendsCommonStock", "Dividends"):
            self.assertFalse(
                concepts.policy_accepts(declared, "common_dividends_paid", "USD"),
                declared,
            )

    def test_dividends_paid_outranks_the_all_inclusive_total(self):
        """보통주 전용 태그가 있으면 우선주·비지배까지 포함한 총액보다 먼저다."""
        self.assertLess(
            concepts.policy_priority(
                "PaymentsOfDividendsCommonStock", "common_dividends_paid"
            ),
            concepts.policy_priority("PaymentsOfDividends", "common_dividends_paid"),
        )

    def test_cash_flow_totals_reject_line_items(self):
        totals = {
            "net_cash_from_operating_activities": (
                "NetCashProvidedByUsedInOperatingActivities",
                "IncreaseDecreaseInOperatingLeaseLiability",
            ),
            "net_cash_from_investing_activities": (
                "NetCashProvidedByUsedInInvestingActivities",
                "PaymentsForProceedsFromOtherInvestingActivities",
            ),
            "net_cash_from_financing_activities": (
                "NetCashProvidedByUsedInFinancingActivities",
                "PaymentsRelatedToTaxWithholdingForShareBasedCompensation",
            ),
        }
        for column, (total, line_item) in totals.items():
            self.assertTrue(concepts.policy_accepts(total, column, "USD"), total)
            self.assertFalse(
                concepts.policy_accepts(line_item, column, "USD"), line_item
            )

    def test_capex_rejects_the_non_cash_accrual_disclosure(self):
        """CapitalExpendituresIncurredButNotYetPaid는 미지급 발생액 주석이라
        현금유출이 아니다."""
        self.assertTrue(
            concepts.policy_accepts(
                "PaymentsToAcquirePropertyPlantAndEquipment",
                "capital_expenses",
                "USD",
            )
        )
        self.assertFalse(
            concepts.policy_accepts(
                "CapitalExpendituresIncurredButNotYetPaid",
                "capital_expenses",
                "USD",
            )
        )

    def test_buyback_excludes_preferred_and_noncontrolling_repurchases(self):
        self.assertTrue(
            concepts.policy_accepts(
                "PaymentsForRepurchaseOfCommonStock",
                "stock_repurchase_payments",
                "USD",
            )
        )
        for rejected in (
            "PaymentsForRepurchaseOfPreferredStockAndPreferenceStock",
            "PaymentsForRepurchaseOfRedeemableNoncontrollingInterest",
        ):
            self.assertFalse(
                concepts.policy_accepts(
                    rejected, "stock_repurchase_payments", "USD"
                ),
                rejected,
            )


if __name__ == "__main__":
    unittest.main()
