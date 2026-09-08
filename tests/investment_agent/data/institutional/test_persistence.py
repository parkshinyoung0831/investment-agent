"""institutional v1 저장소 경계를 검증한다."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from investment_agent.data.institutional import persistence as db

from investment_agent.data.institutional.application import retention
from investment_agent.data.institutional.infrastructure.sources.openfigi import MappingResult
from tests.investment_agent.fakes import FakeDatabase


class MappingCacheTest(unittest.TestCase):
    def test_mapping_conclusions_are_cached_in_universe(self) -> None:
        fake = FakeDatabase()
        fake.put("universe", "securities", [{"security_id": 1, "ticker": "AAPL"}])
        db.configure(fake)
        mapping = [
            MappingResult(
                "037833100", "CUSIP", "AAPL", "BBG000B9XRY4", "mapped", "openfigi"
            )
        ]

        stored = db.cache_mappings(mapping, universe_tickers={"AAPL"})

        self.assertEqual(stored, 1)
        schema_table, rows, conflict = fake.upserts[0]
        self.assertEqual(("universe", "security_identifiers"), schema_table)
        self.assertEqual("identifier,identifier_type,valid_from", conflict)
        row = rows[0]
        self.assertEqual(row["mapping_status"], "mapped")
        self.assertNotIn("error", row)

    def test_domain_conclusions_have_a_thirty_day_recheck_window(self) -> None:
        now = datetime(2026, 8, 27, tzinfo=timezone.utc)
        recent = {
            "mapping_status": "not_found",
            "updated_at": (now - timedelta(days=29)).isoformat(),
        }
        due = {**recent, "updated_at": (now - timedelta(days=31)).isoformat()}

        self.assertFalse(db.mapping_is_due(recent, now=now))
        self.assertTrue(db.mapping_is_due(due, now=now))
        self.assertFalse(
            db.mapping_is_due(
                {"mapping_status": "historical", "updated_at": "2000-01-01T00:00:00Z"},
                now=now,
            )
        )


class InstitutionalRetentionTest(unittest.TestCase):
    def test_prune_history_calls_db_with_5_years_ago(self):
        with patch.object(retention.db, "delete_filings_before", return_value=7) as mock_delete:
            deleted = retention.prune_history(today=date(2026, 9, 2))

        self.assertEqual(deleted, 7)
        mock_delete.assert_called_once_with("2021-09-02")

    def test_prune_history_handles_leap_year(self):
        with patch.object(retention.db, "delete_filings_before", return_value=0) as mock_delete:
            deleted = retention.prune_history(today=date(2024, 2, 29))

        self.assertEqual(deleted, 0)
        mock_delete.assert_called_once_with("2019-02-28")

    def test_db_delete_filings_before_uses_v1_repository(self):
        with patch.object(retention.db, "_repository") as repo_factory:
            repo_factory.return_value.delete_filings_before.return_value = 2
            deleted = retention.db.delete_filings_before("2021-09-02")

        self.assertEqual(deleted, 2)
        repo_factory.return_value.delete_filings_before.assert_called_once_with(
            date(2021, 9, 2)
        )


if __name__ == "__main__":
    unittest.main()
