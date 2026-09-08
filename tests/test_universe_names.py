"""Universe 핵심 갱신과 로컬 전용 한글명 보강의 경계 테스트."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from investment_agent.data.universe import persistence as db
from investment_agent.data.universe.application import collection as etl
from investment_agent.data.universe.commands import (
    universe_membership as membership,
    universe_monthly as monthly,
    universe_names as names,
)


class KoreanNameSelectionTest(unittest.TestCase):
    def test_pending_names_are_limited_to_tracked_missing_rows(self):
        fake_db = mock.Mock()
        fake_db.select_in_chunks.return_value = [
            {"cik": "0000320193", "company_name_ko": None}
        ]
        with (
            mock.patch.object(db, "_security_rows", return_value=[
                {"ticker": "AAPL", "cik": "0000320193", "is_tracked": True}
            ]),
            mock.patch.object(db, "_db", return_value=fake_db),
        ):
            rows = db.select_name_ko_pending("2026-05-15T00:00:00Z")

        self.assertEqual(rows, ["AAPL"])


class KoreanNameRefreshTest(unittest.TestCase):
    def test_refresh_retries_missing_names_without_overwriting_existing_rows(self):
        with (
            mock.patch.object(
                etl.db,
                "select_name_ko_pending",
                return_value=["AAPL", "MSFT"],
            ) as select_pending,
            mock.patch.object(
                etl,
                "fetch_toss_korean_names",
                return_value=({"AAPL": "애플"}, ["AAPL", "MSFT"]),
            ),
            mock.patch.object(etl.db, "apply_toss_names") as apply_names,
        ):
            updated = etl.refresh_korean_names(retry_after_days=90)

        self.assertEqual(
            updated,
            {"pending": 2, "attempted": 2, "updated": 1},
        )
        retry_before = select_pending.call_args.args[0]
        parsed = datetime.strptime(retry_before, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        age_days = (datetime.now(timezone.utc) - parsed).days
        self.assertIn(age_days, (89, 90))
        apply_names.assert_called_once_with(
            {"AAPL": "애플"},
            ["AAPL", "MSFT"],
        )

    def test_local_entrypoint_forwards_retry_policy(self):
        with mock.patch.object(
            etl,
            "refresh_korean_names",
            return_value={"pending": 0, "attempted": 0, "updated": 0},
        ) as refresh:
            result = names.main(["--retry-after-days", "30"])

        self.assertEqual(result, 0)
        refresh.assert_called_once_with(retry_after_days=30)

    def test_local_entrypoint_fails_when_toss_cannot_query_pending_rows(self):
        with mock.patch.object(
            etl,
            "refresh_korean_names",
            return_value={"pending": 2, "attempted": 0, "updated": 0},
        ):
            result = names.main([])

        self.assertEqual(result, 1)


class UniverseWorkflowBoundaryTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_monthly_entrypoint_does_not_call_toss_enrichment(self):
        with (
            mock.patch.object(etl, "sync_exchange_listings"),
            mock.patch.object(etl, "sync_sec_entities"),
            mock.patch.object(
                etl,
                "reconcile_membership",
                return_value={"changed": False, "added": [], "removed": []},
            ) as reconcile,
            mock.patch.object(etl, "refresh_korean_names") as refresh_names,
        ):
            result = monthly.main([])

        self.assertEqual(result, 0)
        refresh_names.assert_not_called()
        reconcile.assert_called_once_with(audit_history=True)

    def test_membership_entrypoint_is_read_only_when_unchanged(self):
        with (
            mock.patch.object(etl, "sync_exchange_listings"),
            mock.patch.object(
                etl,
                "reconcile_membership",
                return_value={"changed": False, "added": [], "removed": []},
            ) as reconcile,
            mock.patch.object(etl, "sync_sec_entities") as sync_entities,
        ):
            result = membership.main([])

        self.assertEqual(result, 0)
        reconcile.assert_called_once_with(audit_history=False)
        sync_entities.assert_not_called()

    def test_membership_entrypoint_enriches_only_after_change(self):
        with (
            mock.patch.object(etl, "sync_exchange_listings"),
            mock.patch.object(
                etl,
                "reconcile_membership",
                return_value={"changed": True, "added": ["NEW"], "removed": ["OLD"]},
            ),
            mock.patch.object(etl, "sync_sec_entities") as sync_entities,
        ):
            result = membership.main([])

        self.assertEqual(result, 0)
        sync_entities.assert_called_once_with(tracked_only=True, sec_get_json=mock.ANY)

    def test_github_workflow_has_no_toss_credentials(self):
        workflow = (self.ROOT / ".github/workflows/universe_monthly.yml").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("TOSS_CLIENT_ID", workflow)
        self.assertNotIn("TOSS_CLIENT_SECRET", workflow)


if __name__ == "__main__":
    unittest.main()
