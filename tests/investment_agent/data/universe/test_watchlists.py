"""Supabase 관심종목 관리와 공시 필터 규칙을 검증한다."""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


if "supabase" not in sys.modules:
    supabase = types.ModuleType("supabase")
    supabase.Client = object
    supabase.create_client = lambda *_args, **_kwargs: None
    sys.modules["supabase"] = supabase

from investment_agent.data.universe.watchlists import db as alerts_db
from investment_agent.notifications.earnings_report import candidates
from investment_agent.reporting.notifications import earnings_report as fundamentals_db
from investment_agent.operations.commands import fundamentals_pending as pending


class WatchlistNormalizationTest(unittest.TestCase):
    def test_normalize_ticker(self):
        self.assertEqual(alerts_db.normalize_ticker("  aapl "), "AAPL")

    def test_empty_ticker_is_rejected(self):
        with self.assertRaises(ValueError):
            alerts_db.normalize_ticker("   ")


class PendingFilingGroupsTest(unittest.TestCase):
    def test_membership_date_blocks_older_filings(self):
        members = [
            {"ticker": "AAPL", "watch_from": "2026-08-10"},
            {"ticker": "MSFT", "watch_from": "2026-08-01"},
        ]
        rows = [
            {"ticker": "AAPL", "accession_no": "A-OLD", "filed_at": "2026-08-09", "fiscal_period": "Q3"},
            {"ticker": "AAPL", "accession_no": "A-NEW", "filed_at": "2026-08-10", "fiscal_period": "Q3"},
            {"ticker": "MSFT", "accession_no": "M-NEW", "filed_at": "2026-08-08", "fiscal_period": "Q4"},
            {"ticker": "NVDA", "accession_no": "N-NEW", "filed_at": "2026-08-12", "fiscal_period": "Q2"},
        ]

        result = candidates.group_by_filing(
            rows,
            processed=set(),
            members=members,
            global_cutoff="2026-08-07",
        )

        self.assertEqual(set(result), {("AAPL", "A-NEW"), ("MSFT", "M-NEW")})

    def test_global_cutoff_and_processed_history_still_apply(self):
        members = [{"ticker": "AAPL", "watch_from": "2026-01-01"}]
        rows = [
            {"ticker": "AAPL", "accession_no": "A-OLD", "filed_at": "2026-08-01", "fiscal_period": "Q2"},
            {"ticker": "AAPL", "accession_no": "A-SENT", "filed_at": "2026-08-10", "fiscal_period": "Q2"},
            {"ticker": "AAPL", "accession_no": "A-FY", "filed_at": "2026-08-11", "fiscal_period": "FY"},
            {"ticker": "AAPL", "accession_no": "A-FY", "filed_at": "2026-08-11", "fiscal_period": "Q4"},
        ]

        result = candidates.group_by_filing(
            rows,
            processed={("AAPL", "A-SENT")},
            members=members,
            global_cutoff="2026-08-07",
        )

        self.assertEqual(list(result), [("AAPL", "A-FY")])
        self.assertEqual(len(result[("AAPL", "A-FY")]), 2)

    def test_same_date_different_accessions_are_distinct(self):
        members = [{"ticker": "AAPL", "watch_from": "2026-01-01"}]
        rows = [
            {"ticker": "AAPL", "accession_no": "A-1", "filed_at": "2026-08-11"},
            {"ticker": "AAPL", "accession_no": "A-2", "filed_at": "2026-08-11"},
        ]

        result = candidates.group_by_filing(
            rows, processed=set(), members=members, global_cutoff="2026-08-07"
        )

        self.assertEqual(set(result), {("AAPL", "A-1"), ("AAPL", "A-2")})


class PendingStateTest(unittest.TestCase):
    def test_empty_database_watchlist_skips_all_other_queries(self):
        with patch.object(fundamentals_db, "watchlist_members", return_value=[]), patch.object(
            fundamentals_db, "select_all_paged"
        ) as select:
            state = candidates.pending_state()

        self.assertEqual(
            state,
            {"watchlist_count": 0, "pending_filings": 0, "should_notify": False},
        )
        select.assert_not_called()

    def test_github_output_has_report_and_flash_states(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output.txt"
            state = {"watchlist_count": 2, "pending_filings": 1, "should_notify": True}
            with patch.object(
                pending.candidates, "pending_state", return_value=state
            ), patch.object(pending, "pending_count", return_value=2), patch.object(
                pending.Database, "from_config", return_value=object()
            ), patch.object(pending, "EarningsFlashStore", return_value=object()):
                result = pending.main(["--github-output", str(output)])

            self.assertEqual(result, 0)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "should_notify=true\nshould_flash=true\nwatchlist_count=2\n"
                "pending_filings=1\npending_flash=2\n",
            )


if __name__ == "__main__":
    unittest.main()
