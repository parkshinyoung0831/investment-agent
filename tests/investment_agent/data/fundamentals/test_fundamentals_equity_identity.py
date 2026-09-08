"""연결 자본 범위와 비지배지분 파생 규칙의 회귀 테스트."""
from __future__ import annotations

import unittest

from investment_agent.data.fundamentals.domain.services.reported_observations import to_wide_tables


def _fact(
    concept: str,
    column_key: str,
    value: float,
    *,
    cik: str = "0000000001",
    fiscal_year: int = 2025,
    fiscal_period: str = "Q4",
    period_end: str = "2025-12-31",
    filed_at: str = "2026-02-27",
    accession_no: str = "0001193125-26-082531",
) -> dict:
    return {
        "cik": cik,
        "statement": "BS",
        "concept": concept,
        "standard_tag": column_key,
        "column_key": column_key,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "qtrs": 0,
        "form_type": "10-K",
        "period_start": None,
        "period_end": period_end,
        "value": value,
        "unit": "USD",
        "filed_at": filed_at,
        "accession_no": accession_no,
        "is_derived": False,
    }


class ConsolidatedEquityScope(unittest.TestCase):
    def test_total_less_parent_equity_derives_complete_nci_balance(self):
        facts = [
            _fact("Assets", "assets", 47_708_975_000),
            _fact("Liabilities", "liabilities", 25_827_803_000),
            _fact("StockholdersEquity", "common_equity", 8_665_526_000),
            _fact(
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                "common_equity",
                20_500_669_000,
            ),
            # 구성요소 하나만 고르면 4.61B가 빠진다. 총계 차이가 우선해야 한다.
            _fact(
                "NonredeemableNoncontrollingInterest",
                "minority_interest_balance",
                7_224_211_000,
            ),
            _fact(
                "RedeemableNoncontrollingInterestEquityCarryingAmount",
                "mezzanine_equity",
                1_380_503_000,
            ),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["common_equity"], 8_665_526_000)
        self.assertEqual(row["minority_interest_balance"], 11_835_143_000)
        self.assertEqual(
            row["source_manifest"]["minority_interest_balance"]["derivation"][
                "formula"
            ],
            "total_equity_including_nci - parent_equity",
        )
        self.assertEqual(
            row["assets"],
            row["liabilities"]
            + row["common_equity"]
            + row["minority_interest_balance"]
            + row["mezzanine_equity"],
        )

    def test_total_equity_fallback_records_that_nci_is_already_included(self):
        facts = [
            _fact("Assets", "assets", 100),
            _fact("Liabilities", "liabilities", 60),
            _fact(
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                "common_equity",
                40,
            ),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertEqual(rows[0]["common_equity_scope"], "stockholders_including_nci")
        self.assertIsNone(rows[0]["minority_interest_balance"])

    def test_inconsistent_total_equity_does_not_invent_nci(self):
        facts = [
            _fact("Assets", "assets", 4_744_000_000),
            _fact("Liabilities", "liabilities", 12_648_000_000),
            _fact("StockholdersEquity", "common_equity", -7_904_000_000),
            _fact(
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                "common_equity",
                -324_000_000,
            ),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertIsNone(rows[0]["minority_interest_balance"])
        self.assertEqual(
            rows[0]["assets"],
            rows[0]["liabilities"] + rows[0]["common_equity"],
        )

    def test_off_balance_date_temporary_equity_is_not_carried_into_q4(self):
        common = {
            "cik": "0000000003",
            "fiscal_year": 2018,
            "period_end": "2018-12-31",
            "filed_at": "2019-03-13",
            "accession_no": "0001682852-19-000009",
        }
        facts = [
            _fact("Assets", "assets", 1_962_149_000, **common),
            _fact("Liabilities", "liabilities", 431_908_000, **common),
            _fact("StockholdersEquity", "common_equity", 1_530_241_000, **common),
            _fact(
                "TemporaryEquityCarryingAmountAttributableToParent",
                "mezzanine_equity",
                1_833_561_000,
                **{**common, "period_end": "2018-12-11"},
            ),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertIsNone(rows[0]["mezzanine_equity"])
        self.assertEqual(
            rows[0]["assets"],
            rows[0]["liabilities"] + rows[0]["common_equity"],
        )

    def test_non_overlapping_temporary_equity_components_are_summed(self):
        facts = [
            _fact("Assets", "assets", 24_390_000_000),
            _fact("Liabilities", "liabilities", 18_602_000_000),
            _fact("StockholdersEquity", "common_equity", -8_432_000_000),
            _fact(
                "TemporaryEquityCarryingAmountAttributableToParent",
                "mezzanine_equity",
                14_224_000_000,
            ),
            _fact(
                "RedeemableNoncontrollingInterestEquityCarryingAmount",
                "mezzanine_equity",
                -4_000_000,
            ),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertEqual(rows[0]["mezzanine_equity"], 14_220_000_000)
        self.assertEqual(
            rows[0]["source_manifest"]["mezzanine_equity"]["derivation"]["formula"],
            "sum(non_overlapping_temporary_equity_components)",
        )
        self.assertEqual(
            rows[0]["assets"],
            rows[0]["liabilities"]
            + rows[0]["common_equity"]
            + rows[0]["mezzanine_equity"],
        )

    def test_duplicate_temporary_equity_aliases_are_not_summed(self):
        facts = [
            _fact("Assets", "assets", 42_938_000_000),
            _fact("Liabilities", "liabilities", 22_088_000_000),
            _fact("StockholdersEquity", "common_equity", 19_882_000_000),
            _fact(
                "TemporaryEquityCarryingAmountAttributableToParent",
                "mezzanine_equity",
                968_000_000,
            ),
            _fact(
                "RedeemableNoncontrollingInterestEquityPreferredCarryingAmount",
                "mezzanine_equity",
                968_000_000,
            ),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertEqual(rows[0]["mezzanine_equity"], 968_000_000)
        self.assertEqual(
            rows[0]["assets"],
            rows[0]["liabilities"]
            + rows[0]["common_equity"]
            + rows[0]["mezzanine_equity"],
        )

    def test_balance_totals_derive_only_missing_mezzanine_equity(self):
        facts = [
            _fact("Assets", "assets", 16_535_929_000),
            _fact("Liabilities", "liabilities", 13_084_629_000),
            _fact("StockholdersEquity", "common_equity", 1_161_499_000),
            _fact(
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                "common_equity",
                2_420_568_000,
            ),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertEqual(rows[0]["minority_interest_balance"], 1_259_069_000)
        self.assertEqual(rows[0]["mezzanine_equity"], 1_030_732_000)
        self.assertEqual(
            rows[0]["source_manifest"]["mezzanine_equity"]["derivation"]["formula"],
            "assets - liabilities - total_equity_including_nci",
        )
        self.assertEqual(
            rows[0]["assets"],
            rows[0]["liabilities"]
            + rows[0]["common_equity"]
            + rows[0]["minority_interest_balance"]
            + rows[0]["mezzanine_equity"],
        )

    def test_total_equity_below_parent_cannot_anchor_mezzanine(self):
        facts = [
            _fact("Assets", "assets", 228_430_000_000, cik="0000000002"),
            _fact("Liabilities", "liabilities", 209_772_000_000, cik="0000000002"),
            _fact(
                "StockholdersEquity",
                "common_equity",
                18_658_000_000,
                cik="0000000002",
            ),
            _fact(
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                "common_equity",
                987_000_000,
                cik="0000000002",
            ),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertIsNone(rows[0]["mezzanine_equity"])
        self.assertEqual(
            rows[0]["assets"],
            rows[0]["liabilities"] + rows[0]["common_equity"],
        )

    def test_parent_equity_alone_cannot_justify_residual_mezzanine(self):
        facts = [
            _fact("Assets", "assets", 100),
            _fact("Liabilities", "liabilities", 60),
            _fact("StockholdersEquity", "common_equity", 20),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertIsNone(rows[0]["mezzanine_equity"])

    def test_temporary_equity_note_is_excluded_when_totals_already_close(self):
        facts = [
            _fact("Assets", "assets", 12_192_585_000),
            _fact("Liabilities", "liabilities", 7_060_288_000),
            _fact("StockholdersEquity", "common_equity", 5_096_015_000),
            _fact(
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                "common_equity",
                5_132_297_000,
            ),
            _fact(
                "MinorityInterest",
                "minority_interest_balance",
                36_282_000,
            ),
            _fact(
                "TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests",
                "mezzanine_equity",
                226_300_000,
            ),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertIsNone(rows[0]["mezzanine_equity"])
        self.assertEqual(
            rows[0]["assets"],
            rows[0]["liabilities"]
            + rows[0]["common_equity"]
            + rows[0]["minority_interest_balance"],
        )

    def test_reported_redeemable_nci_is_kept_when_totals_corroborate_it(self):
        facts = [
            _fact("Assets", "assets", 6_730_396_000),
            _fact("Liabilities", "liabilities", 3_321_956_000),
            _fact("StockholdersEquity", "common_equity", 2_793_066_000),
            _fact(
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                "common_equity",
                2_800_804_000,
            ),
            _fact(
                "MinorityInterest", "minority_interest_balance", 7_738_000
            ),
            _fact(
                "RedeemableNoncontrollingInterestEquityFairValue",
                "mezzanine_equity",
                607_636_000,
            ),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertEqual(rows[0]["mezzanine_equity"], 607_636_000)
        self.assertEqual(
            rows[0]["assets"],
            rows[0]["liabilities"]
            + rows[0]["common_equity"]
            + rows[0]["minority_interest_balance"]
            + rows[0]["mezzanine_equity"],
        )

    def test_spac_trust_guard_allows_balance_residual_mezzanine(self):
        facts = [
            _fact("Assets", "assets", 692_424_839),
            _fact("Liabilities", "liabilities", 25_073_278),
            _fact("StockholdersEquity", "common_equity", 5_000_009),
            _fact("AssetsHeldInTrust", "assets_held_in_trust", 690_613_686),
        ]

        rows, anomalies = to_wide_tables(facts)

        self.assertEqual(anomalies, [])
        self.assertEqual(rows[0]["mezzanine_equity"], 662_351_552)
        self.assertEqual(
            rows[0]["source_manifest"]["mezzanine_equity"]["raw_tag"],
            "DerivedMezzanineEquityFromSpacTrust",
        )
        self.assertEqual(
            rows[0]["assets"],
            rows[0]["liabilities"]
            + rows[0]["common_equity"]
            + rows[0]["mezzanine_equity"],
        )


if __name__ == "__main__":
    unittest.main()
