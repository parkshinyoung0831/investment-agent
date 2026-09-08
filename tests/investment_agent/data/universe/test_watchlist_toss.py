"""토스 보유종목 관심목록 동기화의 안전장치를 검증한다."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


if "supabase" not in sys.modules:
    supabase = types.ModuleType("supabase")
    supabase.Client = object
    supabase.create_client = lambda *_args, **_kwargs: None
    sys.modules["supabase"] = supabase

from investment_agent.data.universe.infrastructure.sources import toss_holdings as toss
from investment_agent.data.universe.watchlists import toss_sync


class TossHoldingsTransformTest(unittest.TestCase):
    def test_only_positive_us_holdings_are_normalized(self):
        items = [
            {"symbol": "aapl", "marketCountry": "US", "quantity": "1.25"},
            {"symbol": "BRK.B", "marketCountry": "US", "quantity": "2"},
            {"symbol": "005930", "marketCountry": "KR", "quantity": "10"},
            {"symbol": "ZERO", "marketCountry": "US", "quantity": "0"},
            {"symbol": "AAPL", "marketCountry": "US", "quantity": "1"},
        ]

        self.assertEqual(toss_sync.held_us_tickers(items), ["AAPL", "BRK-B"])

    def test_malformed_quantity_fails_closed(self):
        with self.assertRaises(toss.TossApiError):
            toss_sync.held_us_tickers(
                [{"symbol": "AAPL", "marketCountry": "US", "quantity": "?"}]
            )

    def test_missing_required_fields_fail_closed(self):
        with self.assertRaises(toss.TossApiError):
            toss_sync.held_us_tickers([{"symbol": "AAPL", "quantity": "1"}])


class TossClientPayloadTest(unittest.TestCase):
    def test_holdings_requires_items_array(self):
        with patch.object(toss, "_authorized_headers", return_value={}), patch.object(
            toss, "_get_json", return_value={"result": {}}
        ):
            with self.assertRaises(toss.TossApiError):
                toss.fetch_holdings(1)

    def test_accounts_require_integer_sequence(self):
        with patch.object(toss, "_authorized_headers", return_value={}), patch.object(
            toss,
            "_get_json",
            return_value={"result": [{"accountSeq": "1"}]},
        ):
            with self.assertRaises(toss.TossApiError):
                toss.fetch_accounts()


class TossSyncWriteBoundaryTest(unittest.TestCase):
    def test_dry_run_never_writes_supabase(self):
        with patch.object(
            toss_sync,
            "collect_toss_holdings",
            return_value=(["AAPL"], {"accounts": 1, "holding_items": 1, "us_tickers": 1}),
        ), patch.object(toss_sync.db, "sync_toss_members") as sync:
            result = toss_sync.sync_toss_holdings(dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["tickers"], ["AAPL"])
        sync.assert_not_called()

    def test_complete_snapshot_is_written_once(self):
        with patch.object(
            toss_sync,
            "collect_toss_holdings",
            return_value=(
                ["AAPL", "MSFT"],
                {"accounts": 1, "holding_items": 2, "us_tickers": 2},
            ),
        ), patch.object(
            toss_sync.db,
            "sync_toss_members",
            return_value={"added": 2, "removed": 0, "skipped_tickers": []},
        ) as sync:
            result = toss_sync.sync_toss_holdings()

        sync.assert_called_once_with(["AAPL", "MSFT"])
        self.assertEqual(result["added"], 2)


class TossMacOnlyConfigurationTest(unittest.TestCase):
    def test_no_github_workflow_runs_toss_holdings_sync(self):
        workflows = Path(".github/workflows")
        contents = "\n".join(
            path.read_text(encoding="utf-8") for path in workflows.glob("*.yml")
        )
        self.assertNotIn("src.pipelines", contents)

    def test_watchlist_is_one_source_aware_column_on_the_issuer_row(self):
        """관심 원장을 따로 두면 "활성인가"의 정의가 두 곳에 생긴다."""
        sql = Path("db/postgres/v1/10_universe.sql").read_text(encoding="utf-8")
        self.assertNotIn("universe.watchlist_members", sql)
        entities_start = sql.index("CREATE TABLE IF NOT EXISTS universe.entities")
        entities = sql[entities_start:sql.index("\n);", entities_start)]
        self.assertIn("watchlist_sources", entities)
        self.assertIn("CHECK (watchlist_sources <@ ARRAY['manual', 'toss']::text[])", entities)
        self.assertIn("watch_from", entities)
        self.assertIn("watchlist_removed_at", entities)
        self.assertNotIn("watchlist_sync_toss", sql)
        for removed_column in (
            "manual_added_at",
            "toss_first_seen_at",
            "toss_last_seen_at",
        ):
            self.assertNotIn(f"{removed_column} ", sql)
        self.assertNotIn("alerts.external_watchlist_members", sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS alerts.watchlists", sql)


if __name__ == "__main__":
    unittest.main()
