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
from tests.investment_agent.notifications.fakes import memory_context


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
            members=members,
            global_cutoff="2026-08-07",
        )

        self.assertEqual(set(result), {("AAPL", "A-NEW"), ("MSFT", "M-NEW")})

    def test_global_cutoff_still_applies_and_filings_group_by_accession(self):
        members = [{"ticker": "AAPL", "watch_from": "2026-01-01"}]
        rows = [
            {"ticker": "AAPL", "accession_no": "A-OLD", "filed_at": "2026-08-01", "fiscal_period": "Q2"},
            {"ticker": "AAPL", "accession_no": "A-FY", "filed_at": "2026-08-11", "fiscal_period": "FY"},
            {"ticker": "AAPL", "accession_no": "A-FY", "filed_at": "2026-08-11", "fiscal_period": "Q4"},
        ]

        result = candidates.group_by_filing(rows, members=members, global_cutoff="2026-08-07")

        self.assertEqual(list(result), [("AAPL", "A-FY")])
        self.assertEqual(len(result[("AAPL", "A-FY")]), 2)

    def test_pending_counts_only_filings_the_ledger_has_not_sent(self):
        """이미 보낸 공시는 원장이 가른다 — 후보 묶음이 아니라 원장 상태로 센다."""
        context, ledger, _channel = memory_context()
        members = [{"ticker": "AAPL", "watch_from": "2026-01-01"}]
        rows = [
            {"ticker": "AAPL", "accession_no": "A-SENT", "filed_at": "2099-08-10", "fiscal_period": "Q2"},
            {"ticker": "AAPL", "accession_no": "A-NEW", "filed_at": "2099-08-11", "fiscal_period": "Q3"},
        ]
        sent = candidates.filing_notice(rows[0])
        ledger.reserve(candidates.TOPIC.name, [{"subject": sent.subject, "occurrence": sent.occurrence,
                                                "revision": sent.revision, "fact_at": sent.fact_at}],
                       owner="old", lease_seconds=60, revisable=False)
        ledger.finish(candidates.TOPIC.name, [sent.key], owner="old", action="create", outcome="sent",
                      location_id="1", message_id="2", failure_code=None, retry_seconds=None)
        with (
            patch.object(fundamentals_db, "watchlist_members", return_value=members),
            patch.object(fundamentals_db, "load_pending_keys", return_value=rows),
            patch.object(candidates, "_cutoff", return_value="2026-08-07"),
        ):
            state = candidates.pending_state(ledger)

        self.assertEqual((state["pending_filings"], state["should_notify"]), (1, True))

    def test_same_date_different_accessions_are_distinct(self):
        members = [{"ticker": "AAPL", "watch_from": "2026-01-01"}]
        rows = [
            {"ticker": "AAPL", "accession_no": "A-1", "filed_at": "2026-08-11"},
            {"ticker": "AAPL", "accession_no": "A-2", "filed_at": "2026-08-11"},
        ]

        result = candidates.group_by_filing(rows, members=members, global_cutoff="2026-08-07")

        self.assertEqual(set(result), {("AAPL", "A-1"), ("AAPL", "A-2")})


class PendingStateTest(unittest.TestCase):
    def test_empty_database_watchlist_skips_all_other_queries(self):
        with patch.object(fundamentals_db, "watchlist_members", return_value=[]), patch.object(
            fundamentals_db, "select_all_paged"
        ) as select:
            state = candidates.pending_state(memory_context()[1])

        self.assertEqual(
            state,
            {"watchlist_count": 0, "pending_filings": 0, "should_notify": False},
        )
        select.assert_not_called()

    def test_github_output_has_report_and_flash_states(self):
        context, _ledger, _channel = memory_context()
        flash_items = [
            {"flash": {"ticker": "NVDA", "accession_no": accession, "filed_at": "2099-08-26"}, "names": {}}
            for accession in ("0001-26-000001", "0001-26-000002")
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output.txt"
            state = {"watchlist_count": 2, "pending_filings": 1, "should_notify": True}
            with (
                patch.object(pending.candidates, "pending_state", return_value=state),
                patch.object(pending, "load_config", return_value=None),
                patch.object(pending, "default_context", return_value=context),
                patch.object(pending.EarningsFlashStore, "configured", return_value=object()),
                patch.object(pending, "load_flash_candidates", return_value=flash_items),
            ):
                result = pending.main(["--github-output", str(output)])

            self.assertEqual(result, 0)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "should_notify=true\nshould_flash=true\nwatchlist_count=2\n"
                "pending_filings=1\npending_flash=2\n",
            )


if __name__ == "__main__":
    unittest.main()
