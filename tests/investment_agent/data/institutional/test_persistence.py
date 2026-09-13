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
        fake.put("universe", "securities", [{"security_id": 1, "ticker": "AAPL", "cik": "0000320193",
                                              "is_active_listing": True, "is_identity_verified": True}])
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
        self.assertEqual("identifier_type,namespace,identifier,security_id,valid_from", conflict)
        row = rows[0]
        self.assertEqual((row["mapping_status"], row["security_id"]), ("verified", 1))
        self.assertIsNone(row["valid_from"])
        self.assertIn("figi=BBG000B9XRY4", row["evidence_ref"])
        self.assertNotIn("error", row)
        # 확인된 연결이 생기면 옛 미확인 행을 지운다.
        self.assertEqual([("universe", "security_identifiers")], [key for key, _eq in fake.deletes])

    def test_a_ticker_nobody_lists_now_is_unresolved_not_guessed(self) -> None:
        """OpenFIGI의 ticker는 지금 표기다. 상장이 끝났으면 다른 회사가 재사용했을 수 있다."""
        fake = FakeDatabase()
        fake.put("universe", "securities", [{"security_id": 5, "ticker": "TWTR", "cik": None,
                                              "is_active_listing": False, "is_identity_verified": False}])
        db.configure(fake)
        mapping = [MappingResult("90184L102", "CUSIP", "TWTR", None, "mapped", "openfigi")]
        db.cache_mappings(mapping, universe_tickers=set())
        row = fake.upserts[0][1][0]
        self.assertEqual((row["mapping_status"], row["security_id"]), ("unresolved", None))
        self.assertIn("ticker=TWTR", row["evidence_ref"])

    def test_domain_conclusions_have_a_thirty_day_recheck_window(self) -> None:
        now = datetime(2026, 8, 27, tzinfo=timezone.utc)
        recent = {
            "mapping_status": "unresolved",
            "updated_at": (now - timedelta(days=29)).isoformat(),
        }
        due = {**recent, "updated_at": (now - timedelta(days=31)).isoformat()}

        self.assertFalse(db.mapping_is_due(recent, now=now))
        self.assertTrue(db.mapping_is_due(due, now=now))
        self.assertFalse(
            db.mapping_is_due(
                {"mapping_status": "verified", "updated_at": "2000-01-01T00:00:00Z"},
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
