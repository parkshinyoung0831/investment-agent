from __future__ import annotations

import unittest

from investment_agent.operations.commands.approve_paper import validate_paper_scope


class ApprovePaperScopeTest(unittest.TestCase):
    def test_partial_tradingagents_batch_is_research_only(self):
        with self.assertRaisesRegex(RuntimeError, "full_portfolio"):
            validate_paper_scope(
                {"metadata": {"coverage": "partial_universe"}, "account_snapshot_id": "snap-1"},
                approved_weights={"AAPL": 0.1, "CASH": 0.9},
                current_tracked={"AAPL"},
            )

    def test_cash_placeholder_cannot_become_paper_order(self):
        with self.assertRaisesRegex(RuntimeError, "account_snapshot_id"):
            validate_paper_scope(
                {"metadata": {"coverage": "full_portfolio"}, "account_snapshot_id": None},
                approved_weights={"AAPL": 0.1, "CASH": 0.9},
                current_tracked={"AAPL"},
            )

    def test_current_tracked_membership_is_rechecked_for_buys(self):
        with self.assertRaisesRegex(RuntimeError, "outside the current tracked universe"):
            validate_paper_scope(
                {"metadata": {"coverage": "full_portfolio"}, "account_snapshot_id": "snap-1"},
                approved_weights={"MSFT": 0.1, "CASH": 0.9},
                current_tracked={"AAPL"},
            )

    def test_full_fresh_in_scope_proposal_passes(self):
        validate_paper_scope(
            {"metadata": {"coverage": "full_portfolio"}, "account_snapshot_id": "snap-1"},
            approved_weights={"AAPL": 0.1, "CASH": 0.9},
            current_tracked={"AAPL"},
        )


if __name__ == "__main__":
    unittest.main()
