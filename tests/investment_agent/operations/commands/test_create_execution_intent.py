from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.operations.commands.create_execution_intent import (
    create_execution_intent,
    validate_promoted_execution_scope,
)

NOW = datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc)


def proposal(**changes):
    value = {
        "stage": "live",
        "account_snapshot_id": "execution_snapshot_1",
        "model_artifact_id": "artifact_1",
        "metadata": {
            "coverage": "full_portfolio",
            "execution_eligible": True,
            "snapshot_captured_at": "2026-08-22T00:59:00+00:00",
        },
    }
    value.update(changes)
    return value


class CreateExecutionIntentScopeTest(unittest.TestCase):
    def test_fresh_live_proposal_returns_artifact(self):
        result = validate_promoted_execution_scope(
            proposal(), execution_mode="live", approved_weights={"AAPL": 0.1, "CASH": 0.9},
            current_tracked={"AAPL"}, now=NOW,
        )
        self.assertEqual(result, "artifact_1")

    def test_shadow_proposal_cannot_be_relabelled_live(self):
        with self.assertRaisesRegex(RuntimeError, "live-stage"):
            validate_promoted_execution_scope(
                proposal(stage="shadow"), execution_mode="live",
                approved_weights={"AAPL": 0.1, "CASH": 0.9},
                current_tracked={"AAPL"}, now=NOW,
            )

    def test_public_core_returns_the_persisted_intent(self):
        class Repository:
            def risk_decision(self, risk_decision_id):
                return {
                    "risk_decision_id": risk_decision_id,
                    "proposal_id": "proposal-1",
                    "policy_key": "portfolio-risk-v1",
                    "policy_version": 1,
                    "policy_hash": "a" * 64,
                    "input_hash": "b" * 64,
                    "is_approved": True,
                    "approved_weights": {"AAPL": 0.1, "CASH": 0.9},
                    "violations": [],
                    "adjustments": [],
                    "decided_at": "2026-08-22T00:58:00+00:00",
                }

            def portfolio_proposal(self, proposal_id):
                return proposal(
                    stage="paper",
                    proposal_id=proposal_id,
                    model_artifact_id="artifact-1",
                )

            def current_tracked_tickers(self):
                return ["AAPL"]

            def has_approved_promotion(self, artifact_id, execution_mode):
                return artifact_id == "artifact-1" and execution_mode == "paper"

        class IntentRepository:
            def __init__(self):
                self.rows = []

            def save_intent(self, row):
                self.rows.append(row)

        execution = IntentRepository()
        intent = create_execution_intent(
            risk_decision_id="risk-1",
            execution_mode="paper",
            confirmation="risk-1",
            now=NOW,
            repository=Repository(),
            execution_repository=execution,
        )
        self.assertTrue(intent.intent_id.startswith("intent_"))
        self.assertEqual(intent.risk_decision_id, "risk-1")
        self.assertEqual(intent.proposal_id, "proposal-1")
        self.assertEqual(execution.rows, [intent.as_row()])

    def test_public_core_rejects_wrong_confirmation_before_lookup(self):
        with self.assertRaisesRegex(RuntimeError, "exactly match"):
            create_execution_intent(
                risk_decision_id="risk-1",
                execution_mode="paper",
                confirmation="risk-2",
                now=NOW,
            )

    def test_stale_snapshot_fails_closed(self):
        stale = proposal(metadata={
            "coverage": "full_portfolio", "execution_eligible": True,
            "snapshot_captured_at": "2026-08-22T00:00:00+00:00",
        })
        with self.assertRaisesRegex(RuntimeError, "stale"):
            validate_promoted_execution_scope(
                stale, execution_mode="live", approved_weights={"AAPL": 0.1, "CASH": 0.9},
                current_tracked={"AAPL"}, now=NOW,
            )


if __name__ == "__main__":
    unittest.main()
