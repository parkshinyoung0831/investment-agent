"""Portfolio 화면의 Runtime read model은 Reporting이 소유한다."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from investment_agent.reporting.readers import dashboard as readers


def _uncached(function):
    return getattr(function, "__wrapped__", function)


class PortfolioReaderTest(unittest.TestCase):
    def test_account_reader_uses_the_latest_safe_snapshot(self) -> None:
        rows = [
            {"captured_at": "2026-09-01T00:00:00Z", "equity": 100},
            {"captured_at": "2026-09-02T00:00:00Z", "equity": 125},
        ]
        with patch.object(readers, "read_runtime_rows", return_value=rows) as read:
            result = _uncached(readers.load_latest_account_snapshot)()
        read.assert_called_once_with("account_snapshots")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.value["equity"], 125)
        self.assertEqual(result.value["holdings"], [])
        self.assertEqual(result.observed_at, "2026-09-02T00:00:00Z")

    def test_target_reader_excludes_follow_plans_and_unapproved_decisions(self) -> None:
        rows = {
            "portfolio_proposals": [
                {"proposal_id": "system", "metadata": {"system_policy": True}, "as_of_at": "2026-09-01"},
                {"proposal_id": "follow", "metadata": {}, "as_of_at": "2026-09-03"},
            ],
            "risk_decisions": [
                {"proposal_id": "system", "is_approved": True, "decided_at": "2026-09-02"},
                {"proposal_id": "follow", "is_approved": True, "decided_at": "2026-09-03"},
                {"proposal_id": "system", "is_approved": False, "decided_at": "2026-09-04"},
            ],
        }
        with patch.object(readers, "read_runtime_rows", side_effect=lambda name: rows[name]):
            result = _uncached(readers.load_latest_target)()
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.value["risk_decision"]["proposal_id"], "system")
        self.assertEqual(result.value["proposal"]["proposal_id"], "system")

    def test_system_portfolio_reader_preserves_offline_fail_closed_status(self) -> None:
        with (
            patch.dict("os.environ", {"DASHBOARD_OFFLINE": "on"}),
            patch.object(readers, "read_runtime_rows") as read,
        ):
            result = _uncached(readers.load_system_portfolio_data)()
        self.assertEqual(result.status, "offline")
        read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
