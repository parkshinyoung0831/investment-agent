"""fundamentals wide 적재의 의미 선택·출처 보존 계약을 검증한다."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from investment_agent.data.fundamentals.domain.services import reported_observations as wide
from investment_agent.data.fundamentals.domain.taxonomy import financial_columns as columns
from investment_agent.data.fundamentals.domain.taxonomy import gaap_concepts as concepts
from investment_agent.reporting.services.earnings import metrics


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
    filed_at: str = "2026-04-30",
    unit: str = "USD",
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
        "unit": unit,
        "filed_at": filed_at,
        "accession_no": accession_no,
        "is_derived": False,
    }


class SemanticPolicyTest(unittest.TestCase):
    def test_common_equity_uses_explicit_tag_priority(self):
        selected, anomalies = wide.select_semantic_candidates([
            _fact("StockholdersEquity", "common_equity", 120),
            _fact("CommonStockholdersEquity", "common_equity", 100),
        ])

        self.assertEqual(anomalies, [])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["concept"], "CommonStockholdersEquity")
        self.assertEqual(selected[0]["value"], 100)

    def test_restricted_cash_is_not_an_eligible_source(self):
        self.assertTrue(
            concepts.is_excluded_tag(
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
            )
        )
        self.assertFalse(
            concepts.policy_accepts(
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                "cash_and_cash_equivalents",
                "USD",
            )
        )

    def test_total_debt_prevents_component_double_counting(self):
        row = {
            "total_debt_including_current": 100,
            "short_term_debt": 20,
            "current_portion_of_long_term_debt": 10,
            "long_term_debt": 80,
        }
        self.assertEqual(metrics.total_debt(row), 100)


class ManifestTest(unittest.TestCase):
    def test_missing_liabilities_are_derived_with_explicit_provenance(self):
        core, anomalies = wide.to_wide_tables([
            _fact("Assets", "assets", 1000, qtrs=0, period_start=None),
            _fact(
                "CommonStockholdersEquity", "common_equity", 300,
                qtrs=0, period_start=None,
            ),
            _fact(
                "MinorityInterest", "minority_interest_balance", 25,
                qtrs=0, period_start=None,
            ),
            _fact(
                "RedeemableNoncontrollingInterestEquityCarryingAmount",
                "mezzanine_equity", 15, qtrs=0, period_start=None,
            ),
            _fact(
                "PreferredStockValue", "preferred_stock", 20,
                qtrs=0, period_start=None,
            ),
        ])

        self.assertEqual(anomalies, [])
        self.assertEqual(core[0]["liabilities"], 640)
        self.assertTrue(core[0]["is_liabilities_derived"])
        self.assertEqual(core[0]["common_equity"], 300)
        derivation = core[0]["source_manifest"]["liabilities"]["derivation"]
        self.assertEqual(
            derivation["formula"],
            "assets - (common_equity + preferred_stock + minority_interest_balance + mezzanine_equity)",
        )

    def test_equity_including_nci_does_not_double_subtract_nci(self):
        core, anomalies = wide.to_wide_tables([
            _fact("Assets", "assets", 1000, qtrs=0, period_start=None),
            _fact(
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                "common_equity", 400, qtrs=0, period_start=None,
            ),
            _fact(
                "MinorityInterest", "minority_interest_balance", 50,
                qtrs=0, period_start=None,
            ),
            _fact(
                "RedeemableNoncontrollingInterestEquityCarryingAmount",
                "mezzanine_equity", 10, qtrs=0, period_start=None,
            ),
        ])

        self.assertEqual(anomalies, [])
        self.assertEqual(core[0]["liabilities"], 590)
        # 비지배지분 포함 총계에서 비지배지분을 뺀 것이 보통주 자본이다.
        self.assertEqual(core[0]["common_equity"], 350)

    def test_direct_liabilities_are_never_overwritten(self):
        core, anomalies = wide.to_wide_tables([
            _fact("Assets", "assets", 1000, qtrs=0, period_start=None),
            _fact("Liabilities", "liabilities", 650, qtrs=0, period_start=None),
            _fact(
                "CommonStockholdersEquity", "common_equity", 300,
                qtrs=0, period_start=None,
            ),
        ])

        self.assertEqual(anomalies, [])
        self.assertEqual(core[0]["liabilities"], 650)
        self.assertFalse(core[0]["is_liabilities_derived"])

    def test_wide_value_retains_raw_source_manifest(self):
        core, anomalies = wide.to_wide_tables([
            _fact("Revenues", "revenue", 500),
        ])

        self.assertEqual(anomalies, [])
        self.assertEqual(core[0]["accession_no"], "ACC-1")
        self.assertEqual(
            core[0]["source_manifest"]["revenue"],
            {
                "raw_tag": "Revenues",
                "standard_tag": concepts.to_standard_tag("Revenues"),
                "unit": "USD",
                "accession_no": "ACC-1",
                "filed_at": "2026-04-30",
                "period_start": "2026-01-01",
                "period_end": "2026-03-31",
                "is_derived": False,
                "derivation": None,
            },
        )

    def test_derived_q4_records_all_source_accessions(self):
        facts = [
            _fact("Revenues", "revenue", 100, fiscal_period="Q1", accession_no="Q1"),
            _fact(
                "Revenues", "revenue", 250, fiscal_period="Q2", qtrs=2,
                period_start="2026-01-01", period_end="2026-06-30", accession_no="Q2",
            ),
            _fact(
                "Revenues", "revenue", 420, fiscal_period="Q3", qtrs=3,
                period_start="2026-01-01", period_end="2026-09-30", accession_no="Q3",
            ),
            _fact(
                "Revenues", "revenue", 600, fiscal_period="FY", qtrs=4,
                period_start="2026-01-01", period_end="2026-12-31", accession_no="FY",
            ),
        ]

        core, _ = wide.to_wide_tables(facts)
        q4 = next(row for row in core if row["fiscal_period"] == "Q4")
        manifest = q4["source_manifest"]["revenue"]

        self.assertEqual(q4["revenue"], 180)
        self.assertEqual(q4["accession_no"], "FY")
        self.assertTrue(manifest["is_derived"])
        self.assertEqual(manifest["derivation"]["formula"], "fy - q1 - q2 - q3")
        self.assertEqual(
            manifest["derivation"]["source_accessions"], ["FY", "Q1", "Q2", "Q3"]
        )

    def test_average_shares_use_weighted_average_derivation(self):
        facts = [
            _fact(
                "WeightedAverageNumberOfSharesOutstanding", "shares_average", 100,
                fiscal_period="Q1", period_start="2026-01-01", period_end="2026-03-31",
                accession_no="Q1", unit="shares",
            ),
            _fact(
                "WeightedAverageNumberOfSharesOutstanding", "shares_average", 110,
                fiscal_period="Q2", qtrs=2, period_start="2026-01-01",
                period_end="2026-06-30", accession_no="Q2", unit="shares",
            ),
            _fact(
                "WeightedAverageNumberOfSharesOutstanding", "shares_average", 120,
                fiscal_period="Q3", qtrs=3, period_start="2026-01-01",
                period_end="2026-09-30", accession_no="Q3", unit="shares",
            ),
            _fact(
                "WeightedAverageNumberOfSharesOutstanding", "shares_average", 130,
                fiscal_period="FY", qtrs=4, period_start="2026-01-01",
                period_end="2026-12-31", accession_no="FY", unit="shares",
            ),
        ]

        core, _ = wide.to_wide_tables(facts)
        by_period = {row["fiscal_period"]: row for row in core}

        self.assertAlmostEqual(by_period["Q2"]["shares_average"], (110 * 181 - 100 * 90) / 91)
        self.assertAlmostEqual(by_period["Q3"]["shares_average"], (120 * 273 - 110 * 181) / 92)
        self.assertAlmostEqual(
            by_period["Q4"]["shares_average"],
            (130 * 365 - 100 * 90 - by_period["Q2"]["shares_average"] * 91
             - by_period["Q3"]["shares_average"] * 92) / 92,
        )
        self.assertEqual(
            by_period["Q4"]["source_manifest"]["shares_average"]["derivation"]["formula"],
            "weighted_average_fy - weighted_average_q1_q2_q3",
        )


class ValidationTest(unittest.TestCase):
    def test_nonpositive_average_shares_are_quarantined_and_cleared(self):
        from investment_agent.data.fundamentals.domain.services import (
            validate_financial_statements as validate,
        )

        clean, anomalies = validate.check_core_wide([{
            "cik": "0000000001", "fiscal_year": 2026, "fiscal_period": "Q4",
            "filed_at": "2027-02-01", "shares_average": -10,
            "shares_fully_diluted_average": 0,
        }])

        self.assertIsNone(clean[0]["shares_average"])
        self.assertIsNone(clean[0]["shares_fully_diluted_average"])
        self.assertEqual(
            [row["reason"] for row in anomalies],
            ["nonpositive_average_shares", "nonpositive_average_shares"],
        )


    def _check(self, **values):
        from investment_agent.data.fundamentals.domain.services import (
            validate_financial_statements as validate,
        )

        return validate.check_core_wide([{
            "cik": "0000000001", "fiscal_year": 2026, "fiscal_period": "Q2",
            "filed_at": "2026-08-01", "revenue": 1.0, **values,
        }])

    def test_shares_reported_in_millions_are_quarantined(self):
        """MCD는 희석주식수를 719(백만 단위)로 냈다. 양수라 통과하던 값이다."""
        clean, anomalies = self._check(
            shares_fully_diluted_average=719.0, eps_diluted_gaap=3.32,
            net_income_to_common_shareholders=2.39e9, net_income=2.39e9,
        )

        self.assertIsNone(clean[0]["shares_fully_diluted_average"])
        self.assertEqual([row["reason"] for row in anomalies], ["average_shares_scale_mismatch"])

    def test_shares_a_thousand_times_too_large_are_quarantined(self):
        clean, anomalies = self._check(
            shares_fully_diluted_average=82_139_000_000.0, eps_diluted_gaap=1.0,
            net_income=82_139_000.0,
        )

        self.assertIsNone(clean[0]["shares_fully_diluted_average"])
        self.assertEqual(len(anomalies), 1)

    def test_consistent_shares_are_kept_even_when_eps_is_rounded(self):
        clean, anomalies = self._check(
            shares_fully_diluted_average=719_000_000.0, eps_diluted_gaap=3.32,
            net_income_to_common_shareholders=2.39e9, net_income=2.39e9,
        )

        self.assertEqual(clean[0]["shares_fully_diluted_average"], 719_000_000.0)
        self.assertEqual(anomalies, [])

    def test_a_unit_error_clears_only_the_shares_and_keeps_the_reported_eps(self):
        """MCD의 보고 EPS 3.32는 맞다. 틀린 것은 주식수 단위뿐이라 EPS까지 지우지 않는다."""
        clean, _ = self._check(
            shares_fully_diluted_average=719.0, eps_diluted_gaap=3.32,
            net_income_to_common_shareholders=2.39e9, net_income=2.39e9,
        )

        self.assertEqual(clean[0]["eps_diluted_gaap"], 3.32)

    def test_a_mismatch_that_is_not_a_unit_error_clears_both_because_either_may_be_wrong(self):
        """액면분할 전후 값을 섞어 파생한 Q4(NFLX 2025-Q4 EPS -17.14)는 배수가 1,000의 거듭제곱이
        아니다. 어느 쪽이 틀렸는지 알 수 없으니 주식수와 EPS를 함께 비운다."""
        clean, anomalies = self._check(
            shares_fully_diluted_average=3.0e9, eps_diluted_gaap=1.0, net_income=1.0e7,
        )

        self.assertIsNone(clean[0]["shares_fully_diluted_average"])
        self.assertIsNone(clean[0]["eps_diluted_gaap"])
        self.assertEqual([row["reason"] for row in anomalies], ["per_share_basis_mismatch"])
        self.assertEqual(anomalies[0]["detail"]["cleared"],
                         ["shares_fully_diluted_average", "eps_diluted_gaap"])

    def test_shares_are_judged_by_either_income_so_one_bad_income_does_not_condemn_them(self):
        """귀속 순이익이 오염(UNH는 63M, 여기서는 1,000배 더 작은 값)돼도 net_income으로는 주식수(906M)가
        EPS와 맞는다. 오염된 쪽만 보고 주식수를 지우면 멀쩡한 값을 잃는다."""
        clean, anomalies = self._check(
            shares_fully_diluted_average=906e6, eps_diluted_gaap=6.04,
            net_income_to_common_shareholders=6.3e4, net_income=5.47e9,
        )

        self.assertEqual(clean[0]["shares_fully_diluted_average"], 906e6)
        self.assertEqual(anomalies, [])

    def test_shares_consistent_with_the_attributable_income_are_kept_when_total_income_is_off(self):
        """반대 방향: 총순이익이 어긋나도 귀속 순이익으로 EPS와 맞으면 주식수를 지우지 않는다."""
        clean, anomalies = self._check(
            shares_fully_diluted_average=500e6, eps_diluted_gaap=2.0,
            net_income_to_common_shareholders=1.0e9, net_income=3.0e12,
        )

        self.assertEqual(clean[0]["shares_fully_diluted_average"], 500e6)
        self.assertEqual(anomalies, [])

    def test_shares_without_eps_or_income_are_left_alone(self):
        clean, anomalies = self._check(shares_fully_diluted_average=719.0, net_income=1e9)

        self.assertEqual(clean[0]["shares_fully_diluted_average"], 719.0)
        self.assertEqual(anomalies, [])


class ViewContractTest(unittest.TestCase):
    def test_ttm_and_multi_class_guards_are_present(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertIn("fundamentals.is_finite_numbers", sql)
        self.assertIn("'unmapped_unlisted'", sql)
        self.assertIn("snapshot_date <= (collected_at AT TIME ZONE 'America/New_York')::date", sql)
        self.assertIn("PRIMARY KEY (cik, period_end)", sql)
        self.assertIn("UNIQUE (cik, fiscal_year, fiscal_period)", sql)
        self.assertIn("PRIMARY KEY (cik, share_class_key, as_of_date, accession_no)", sql)

    def test_views_do_not_depend_on_every_core_column(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertNotIn("SELECT * FROM fundamentals.company_financials", sql)

    def test_view_names_say_whose_fact_they_carry(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        # fundamentals DDL은 writer-owned tables만 둔다. 계산 read model은 reporting 경계에서 소유한다.
        for table in ("filings", "financials", "share_class_snapshots",
                      "segment_metrics", "earnings_results", "earnings_estimates",
                      "earnings_schedule_versions", "analyst_consensus_snapshots"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS fundamentals.{table}", sql)
        self.assertEqual([], re.findall(r"CREATE OR REPLACE VIEW (fundamentals\.\w+)", sql))


class SchemaContractTest(unittest.TestCase):
    def test_obsolete_columns_are_removed(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertNotIn("source_manifest", sql)
        self.assertNotIn("source_archive_sha256", sql)

    def test_derived_liabilities_are_explicit_and_db_validated(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertIn("is_liabilities_derived", sql)
        # 자본은 보통주 자본 한 뜻으로 저장한다 — 범위를 행에 적어 읽는 쪽이 해석하게 하지 않는다.
        self.assertNotIn("common_equity_scope", sql)

    def test_estimates_and_segments_tables_are_absorbed(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertNotIn("CREATE POLICY alerts_sent_read", sql)
        self.assertNotIn("CREATE POLICY filing_runs_read", sql)
        # 검증 실패는 DB 감사 표를 만들지 않고 로그·Actions 사건으로 진단한다 — 파이프라인별 표를
        # 두면 같은 사실이 다른 모양으로 흩어진다.
        self.assertNotIn("CREATE TABLE IF NOT EXISTS fundamentals.validation_failures", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.earnings_estimates", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.segment_metrics", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.earnings_results", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.earnings_schedule_versions", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.analyst_consensus_snapshots", sql)

    def test_a_period_is_one_row_and_restatements_overwrite_it(self):
        """정정 공시는 같은 기간 행을 덮는다. 매핑 규칙이 바뀌면 전체를 다시 처리한다."""
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.financials", sql)
        self.assertIn("PRIMARY KEY (cik, period_end)", sql)
        self.assertIn("available_at timestamptz NOT NULL DEFAULT now()", sql)
        self.assertNotIn("mapping_version", sql)
        self.assertNotIn("financial_versions", sql)
        self.assertNotIn("guard_canonical_financials", sql)

    def test_segment_integrity_rpc_is_private_and_covers_cross_table_contracts(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.filing_processing", sql)
        self.assertIn("content_type    text NOT NULL CHECK (content_type IN ('company', 'segments'))", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.analyst_consensus_snapshots", sql)
        self.assertNotIn("segment_axis_registry", sql)
        self.assertNotIn("segment_concept_registry", sql)
        self.assertNotIn("industry_financials", sql)

    def test_operational_tables_and_expensive_views_are_not_public(self):
        schema_sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")
        self.assertNotIn("GRANT SELECT ON ALL TABLES IN SCHEMA fundamentals", schema_sql)
        self.assertIn("REVOKE ALL ON SCHEMA fundamentals FROM PUBLIC, anon, authenticated", schema_sql)
        self.assertIn("ALTER TABLE fundamentals.filing_processing           ENABLE ROW LEVEL SECURITY", schema_sql)
        self.assertNotIn("fundamentals.filing_runs", schema_sql)
        self.assertNotIn("fundamentals.alerts_sent", schema_sql)


class PersistedPayloadTest(unittest.TestCase):
    """저장 payload에 스키마에 없는 키가 섞이면 그 공시가 통째로 사라진다."""

    def test_memory_only_keys_never_reach_the_table(self):
        from unittest import mock

        from investment_agent.data.fundamentals.infrastructure.supabase import company_financials as repo

        schema = mock.MagicMock()
        schema.table.return_value.upsert.return_value.execute.return_value.data = [{}]
        client = mock.MagicMock()
        client.schema.return_value = schema
        with mock.patch.object(repo, "sb", client), mock.patch.object(
            repo, "select_paged_in_chunks", return_value=[]
        ):
            repo.upsert_core_wide([{
                "cik": "0000000001",
                "period_end": "2026-06-30",
                "accession_no": "0000000001-26-000001",
                "fiscal_year": 2026,
                "fiscal_period": "Q2",
                "revenue": 1.0,
                "source_manifest": {"revenue": {"tag": "Revenues"}},
            }])

        row = schema.table.return_value.upsert.call_args.args[0][0]
        self.assertNotIn("source_manifest", row)
        self.assertEqual(row["revenue"], 1.0)  # 수치는 그대로 남는다

    def test_obsolete_keys_and_schema_agree(self):
        """메모리 전용으로 떼어 내는 키는 스키마가 obsolete로 선언한 것과 같아야 한다."""
        from investment_agent.data.fundamentals.infrastructure.supabase import company_financials as repo

        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")
        for key in repo._MEMORY_ONLY_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(key, sql)


# DDL 선언과 코드 컬럼 목록의 드리프트를 방지하기 위해,
    # v1 DDL의 실제 컬럼 선언과 financial_columns.py의 저장 목록을 직접 대조한다.
class ColumnDriftTest(unittest.TestCase):
    _NUMERIC_COLUMN_RE = re.compile(r"^\s+(\w+)\s+numeric,?\s*$", re.MULTILINE)
    # XBRL 매핑으로 만들어지지 않는 numeric 컬럼. 조정 EPS는 yfinance 발표 결과라
    # CORE_COLUMNS(=SEC facts에서 유도하는 지표) 대조 대상이 아니다.
    _CORE_NON_METRIC_NUMERIC = frozenset({
        "adjusted_eps_actual",
        "adjusted_eps_estimate",
    })

    def _table_body(self, sql: str, table: str) -> str:
        match = re.search(
            rf"CREATE TABLE IF NOT EXISTS fundamentals\.{table} \(.*?\n\);",
            sql,
            re.DOTALL,
        )
        self.assertIsNotNone(match, f"fundamentals.{table} CREATE TABLE 블록을 찾지 못했다")
        return match.group(0)

    def _numeric_columns(self, sql: str, table: str) -> set[str]:
        return set(self._NUMERIC_COLUMN_RE.findall(self._table_body(sql, table)))

    def test_core_wide_sql_matches_all_wide_columns(self):
        """스키마의 numeric 컬럼은 코드가 쓰는 wide 컬럼 전부와 같아야 한다.

        한쪽만 고치면 라이브 스키마가 코드보다 넓거나 좁은 채로 남는다. 좁으면 적재가
        PGRST204로 전부 실패하고, 넓으면 아무도 채우지 않는 컬럼이 방치된다 —
        실제로 두 사고가 모두 있었다.
        """
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")
        declared = self._numeric_columns(sql, "financials") - self._CORE_NON_METRIC_NUMERIC

        self.assertEqual(
            declared,
            set(columns.ALL_WIDE_COLUMNS),
            "db/postgres/v1/30_fundamentals.sql의 financials numeric 컬럼과 columns.ALL_WIDE_COLUMNS가 "
            "어긋난다 — 한쪽만 고치면 라이브 스키마가 코드보다 넓거나 좁은 채로 방치된다.",
        )


if __name__ == "__main__":
    unittest.main()

