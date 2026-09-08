"""SEC entity metadata 원천 결측·TTL·CIK 중복 제거 회귀 테스트."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from investment_agent.data.universe import persistence as db
from investment_agent.data.universe.application import collection as etl
from investment_agent.data.universe.infrastructure.sources import sec_entities as edgar


class EntitySourceTest(unittest.TestCase):
    def test_fetches_each_cik_once_and_promotes_sec_metadata(self):
        payloads = {
            "0000000001": {
                "name": "Example Computers",
                "entityType": "operating",
                "sic": "3571",
                "sicDescription": "Electronic Computers",
                "fiscalYearEnd": "1231",
                "stateOfIncorporation": "CA",
                "formerNames": [{"name": "Old Computers", "from": "2010-01-01", "to": "2020-01-01"}],
            },
            "0000000002": {
                "name": "Example Other",
                "entityType": "other",
                "sic": "",
                "sicDescription": "",
                "formerNames": [],
            },
        }

        def fake_get(url: str):
            cik = url.split("CIK", 1)[1].split(".", 1)[0]
            return payloads[cik]

        get_json = mock.Mock(side_effect=fake_get)
        rows = edgar.fetch_entity_results(["1", "1", "2"], get_json=get_json)

        self.assertEqual(get_json.call_count, 2)
        self.assertEqual([row["cik"] for row in rows], ["0000000001", "0000000002"])
        self.assertEqual(rows[0]["outcome"], "success")
        self.assertEqual(rows[0]["company_name"], "Example Computers")
        self.assertEqual(rows[0]["entity_type"], "operating")
        self.assertEqual(rows[0]["fiscal_year_end"], "1231")
        self.assertEqual(rows[0]["state_of_incorporation"], "CA")
        self.assertEqual(rows[0]["former_names"][0]["name"], "Old Computers")
        self.assertEqual(rows[0]["sic_code"], "3571")
        self.assertEqual(rows[0]["sic_division_name"], "Manufacturing")
        self.assertEqual(rows[1]["outcome"], "source_not_classified")

    def test_description_without_mappable_code_is_mapping_failure(self):
        row = edgar.fetch_entity_results(["3"], get_json=lambda _: {
            "name": "Unmapped Example",
            "entityType": "operating",
            "sic": "1800",
            "sicDescription": "Unmapped test industry",
        })[0]

        self.assertEqual(row["outcome"], "mapping_failure")
        self.assertIsNone(row["sic_division_name"])

    def test_network_failure_becomes_retryable_state(self):
        row = edgar.fetch_entity_results(
            ["4"], get_json=mock.Mock(side_effect=TimeoutError("slow"))
        )[0]

        self.assertEqual(row["outcome"], "retryable_failure")
        self.assertEqual(row["error_code"], "TimeoutError")


class EntitySelectionTest(unittest.TestCase):
    def test_security_profiles_join_entity_once_by_cik(self):
        fake_db = mock.Mock()
        fake_db.select_in_chunks.return_value = [
            {
                "cik": "0001652044",
                "company_name": "Alphabet Inc.",
                "company_name_ko": "구글",
                "sic_industry_name": "Services",
                "sic_division_name": "Services",
            }
        ]
        with mock.patch.object(
            db,
            "_security_rows",
            return_value=[
                {"ticker": "GOOG", "cik": "0001652044"},
                {"ticker": "GOOGL", "cik": "0001652044"},
            ],
        ), mock.patch.object(db, "_db", return_value=fake_db):
            rows = db.select_security_profiles(["GOOG", "GOOGL"])

        self.assertEqual(rows[0]["name"], "Alphabet Inc.")
        self.assertEqual(rows[1]["name"], "Alphabet Inc.")
        self.assertEqual(rows[0]["name_ko"], "구글")
        self.assertEqual(rows[1]["sic_division"], "Services")

    def test_entity_metadata_freshness_controls_retry_without_an_ops_state(self):
        now = datetime(2026, 8, 26, tzinfo=timezone.utc)
        candidates = [
            {"ticker": "NEW", "cik": "0000000001", "is_tracked": True},
            {"ticker": "WAIT", "cik": "0000000002", "is_tracked": False},
            {"ticker": "DUE", "cik": "0000000003", "is_tracked": False},
            {"ticker": "INCOMPLETE", "cik": "0000000004", "is_tracked": False},
        ]
        entities = [
            {
                "cik": "0000000002",
                "entity_type": "operating",
                "sic_code": "3571",
                "sic_industry_name": "Electronic Computers",
                "sic_division_name": "Manufacturing",
                "sec_metadata_updated_at": (now - timedelta(days=89)).isoformat(),
            },
            {
                "cik": "0000000003",
                "entity_type": "operating",
                "sic_code": "3571",
                "sic_industry_name": "Electronic Computers",
                "sic_division_name": "Manufacturing",
                "sec_metadata_updated_at": (now - timedelta(days=91)).isoformat(),
            },
            {
                "cik": "0000000004",
                "entity_type": "other",
                "sic_code": None,
                "sic_industry_name": None,
                "sic_division_name": None,
                "sec_metadata_updated_at": (now - timedelta(days=179)).isoformat(),
            },
        ]
        fake_db = mock.Mock()
        fake_db.select_paged.side_effect = [entities]
        with mock.patch.object(db, "_security_rows", return_value=candidates), mock.patch.object(
            db, "_db", return_value=fake_db
        ):
            rows = db.select_entity_pending(now=now)

        self.assertEqual([row["ticker"] for row in rows], ["NEW", "DUE"])

    def test_entity_sync_deduplicates_tickers_by_cik(self):
        pending = [
            {"ticker": "A", "cik": "0000000001"},
            {"ticker": "A-PA", "cik": "0000000001"},
            {"ticker": "B", "cik": "0000000002"},
        ]
        results = [
            {"cik": "0000000001", "outcome": "source_not_classified"},
            {"cik": "0000000002", "outcome": "success"},
        ]
        with (
            mock.patch.object(etl.db, "select_entity_pending", return_value=pending),
            mock.patch.object(etl, "fetch_entity_results", return_value=results) as fetch,
            mock.patch.object(etl.db, "apply_entity_results", return_value=3) as apply,
        ):
            metrics = etl.sync_sec_entities()

        fetch.assert_called_once_with(
            ["0000000001", "0000000002"], get_json=mock.ANY
        )
        apply.assert_called_once_with(results)
        self.assertEqual(metrics["candidate_entities"], 3)
        self.assertEqual(metrics["unique_ciks"], 2)
        self.assertEqual(metrics["fetched"], 2)
        self.assertEqual(metrics["affected"], 3)

    def test_entity_sync_does_not_persist_retryable_provider_failure(self):
        pending = [{"ticker": "A", "cik": "0000000001"}]
        results = [{"cik": "0000000001", "outcome": "retryable_failure"}]
        with (
            mock.patch.object(etl.db, "select_entity_pending", return_value=pending),
            mock.patch.object(etl, "fetch_entity_results", return_value=results),
            mock.patch.object(etl.db, "apply_entity_results", return_value=0) as apply,
            self.assertRaisesRegex(RuntimeError, "retryable_failures=1"),
        ):
            etl.sync_sec_entities()

        apply.assert_called_once_with([])


class EntitySchemaTest(unittest.TestCase):
    def test_entity_metadata_freshness_is_canonical(self):
        from pathlib import Path

        universe_sql = Path("db/postgres/v1/10_universe.sql").read_text(encoding="utf-8").lower()
        for field in ("entity_type", "sic_code", "fiscal_year_end", "state_of_incorporation", "former_names"):
            self.assertIn(field, universe_sql)
        self.assertIn("sec_metadata_updated_at", universe_sql)
        self.assertIn("updated_at timestamptz", universe_sql)
        self.assertIn("references universe.entities(cik)", universe_sql)
        # 관심은 발행사 행의 상태다 — 별도 원장을 다시 만들면 정의가 둘로 갈라진다.
        self.assertIn("watchlist_sources", universe_sql)
        self.assertIn(
            "is_watchlisted          boolean generated always as "
            "(cardinality(watchlist_sources) > 0) stored",
            universe_sql,
        )
        self.assertNotIn("create table if not exists universe.watchlist_members", universe_sql)

    def test_exchange_master_only_seeds_new_entity_names(self):
        from pathlib import Path

        sql = Path("db/postgres/v1/10_universe.sql").read_text(encoding="utf-8").lower()
        self.assertIn("create table if not exists universe.securities", sql)
        self.assertIn("ticker            text not null unique", sql)
        self.assertIn("is_tracked        boolean not null default false", sql)
        self.assertIn("create table if not exists universe.index_memberships", sql)


if __name__ == "__main__":
    unittest.main()
