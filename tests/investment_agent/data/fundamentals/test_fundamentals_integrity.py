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
        self.assertEqual(metrics._total_debt(row), 100)


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
        self.assertEqual(core[0]["common_equity_scope"], "common")
        derivation = core[0]["source_manifest"]["liabilities"]["derivation"]
        self.assertEqual(
            derivation["formula"],
            "assets - non_liability_claims(common_equity_scope)",
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
        self.assertEqual(
            core[0]["common_equity_scope"], "stockholders_including_nci"
        )

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
        self.assertEqual(core[0]["mapping_version"], concepts.SEMANTIC_POLICY_VERSION)
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


class ViewContractTest(unittest.TestCase):
    def test_ttm_and_multi_class_guards_are_present(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertIn("fundamentals.is_finite_numbers", sql)
        self.assertIn("'unmapped_unlisted'", sql)
        self.assertIn("snapshot_date <= (collected_at AT TIME ZONE 'America/New_York')::date", sql)
        self.assertIn("PRIMARY KEY (cik, period_end, fiscal_period)", sql)
        self.assertIn("PRIMARY KEY (cik, share_class_key, as_of_date, accession_no)", sql)

    def test_views_do_not_depend_on_every_core_column(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertNotIn("SELECT * FROM fundamentals.company_financials", sql)

    def test_view_names_say_whose_fact_they_carry(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        # v1 fundamentals DDL은 writer-owned tables만 선언하고, 계산 read model은
        # reporting 경계에서 소유한다.
        for table in ("filings", "financials", "share_class_snapshots",
                      "segment_metrics", "earnings_results", "earnings_estimates",
                      "earnings_schedule_versions", "analyst_consensus_snapshots"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS fundamentals.{table}", sql)
        self.assertNotIn("CREATE VIEW fundamentals.", sql)


class SchemaContractTest(unittest.TestCase):
    def test_obsolete_columns_are_removed(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertNotIn("source_manifest", sql)
        self.assertNotIn("source_archive_sha256", sql)

    def test_derived_liabilities_are_explicit_and_db_validated(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertIn("is_liabilities_derived", sql)
        self.assertIn("common_equity_scope", sql)
        self.assertIn("PRIMARY KEY (cik, period_end, fiscal_period)", sql)

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

    def test_company_replace_is_state_idempotent_without_timestamp_churn(self):
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")

        self.assertIn("PRIMARY KEY (cik, period_end, fiscal_period)", sql)
        self.assertIn("available_at timestamptz NOT NULL DEFAULT now()", sql)
        self.assertIn("mapping_version text        NOT NULL", sql)

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
        with mock.patch.object(repo, "sb", client):
            repo.upsert_core_wide([{
                "cik": "0000000001",
                "period_end": "2026-06-30",
                "accession_no": "0000000001-26-000001",
                "fiscal_year": 2026,
                "fiscal_period": "Q2",
                "mapping_version": "v1",
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

