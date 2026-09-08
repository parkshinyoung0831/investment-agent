"""Exact Signal Batch and Model Promotion Boundary Tests."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.trading.contracts import ContractError
from investment_agent.operations.commands.create_execution_intent import (
    create_execution_intent,
    validate_promoted_execution_scope,
)
from investment_agent.trading.portfolio.constructor import PortfolioConstructor
from investment_agent.trading.portfolio.contracts import (
    CASH_SYMBOL,
    PortfolioProposal,
    RiskDecision,
    SecurityProposal,
)
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalBook, SignalRecord
from investment_agent.execution.orders.snapshots import PositionSnapshot, AccountSnapshot


class FakeDecisionRepository:
    def __init__(self, proposals: dict, risk_decisions: dict, promoted_artifacts: set[tuple[str, str]]):
        self._proposals = proposals
        self._risk_decisions = risk_decisions
        self._promoted = promoted_artifacts

    def portfolio_proposal(self, proposal_id: str):
        return self._proposals.get(proposal_id)

    def risk_decision(self, risk_decision_id: str):
        return self._risk_decisions.get(risk_decision_id)

    def current_tracked_tickers(self):
        return ["AAPL", "MSFT", "NVDA"]

    def has_approved_promotion(self, artifact_id: str, to_stage: str) -> bool:
        return (artifact_id, to_stage) in self._promoted


class FakeExecutionRepository:
    def __init__(self):
        self.saved_intents = []

    def save_intent(self, intent: dict):
        self.saved_intents.append(intent)


class ExactBatchPromotionBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.as_of_at = "2026-08-25T10:00:00+00:00"
        self.completed_a = "2026-08-25T10:05:00+00:00"
        self.completed_b = "2026-08-25T10:10:00+00:00"
        self.snapshot_at = "2026-08-25T10:15:00+00:00"
        self.decision_at = "2026-08-25T10:20:00+00:00"

        # Batch A: Model A (Live Promoted)
        self.batch_a = SignalBatch(
            batch_id="signal_batch_00000000000000000000000a",
            as_of_at=self.as_of_at,
            completed_at=self.completed_a,
            requested_symbols=("AAPL", "MSFT"),
            successful_symbols=("AAPL", "MSFT"),
            model_artifact_id="model_artifact_a",
        )
        self.proposal_aapl_a = SecurityProposal(
            ticker="AAPL",
            as_of_at=self.as_of_at,
            signal="open",
            probability_up=0.8,
            confidence=0.9,
            expected_excess_return=0.05,
            target_weight=0.3,
            reasoning=("Good",),
            evidence_ids=(),
        )
        self.proposal_msft_a = SecurityProposal(
            ticker="MSFT",
            as_of_at=self.as_of_at,
            signal="open",
            probability_up=0.75,
            confidence=0.85,
            expected_excess_return=0.04,
            target_weight=0.3,
            reasoning=("Solid",),
            evidence_ids=(),
        )
        self.record_aapl_a = SignalRecord(
            batch_id=self.batch_a.batch_id,
            proposal=self.proposal_aapl_a,
            recorded_at=self.completed_a,
            expires_at="2026-08-25T12:00:00+00:00",
        )
        self.record_msft_a = SignalRecord(
            batch_id=self.batch_a.batch_id,
            proposal=self.proposal_msft_a,
            recorded_at=self.completed_a,
            expires_at="2026-08-25T12:00:00+00:00",
        )

        # Batch B: Model B (Shadow / NOT Live Promoted), has newer NVDA and newer AAPL
        self.batch_b = SignalBatch(
            batch_id="signal_batch_00000000000000000000000b",
            as_of_at=self.as_of_at,
            completed_at=self.completed_b,
            requested_symbols=("AAPL", "NVDA"),
            successful_symbols=("AAPL", "NVDA"),
            model_artifact_id="model_artifact_b",
        )
        self.proposal_aapl_b = SecurityProposal(
            ticker="AAPL",
            as_of_at=self.as_of_at,
            signal="open",
            probability_up=0.95,
            confidence=0.99,
            expected_excess_return=0.10,
            target_weight=0.5,
            reasoning=("Newer AAPL from unpromoted model",),
            evidence_ids=(),
        )
        self.proposal_nvda_b = SecurityProposal(
            ticker="NVDA",
            as_of_at=self.as_of_at,
            signal="open",
            probability_up=0.90,
            confidence=0.95,
            expected_excess_return=0.08,
            target_weight=0.4,
            reasoning=("NVDA from unpromoted model",),
            evidence_ids=(),
        )
        self.record_aapl_b = SignalRecord(
            batch_id=self.batch_b.batch_id,
            proposal=self.proposal_aapl_b,
            recorded_at=self.completed_b,
            expires_at="2026-08-25T12:00:00+00:00",
        )
        self.record_nvda_b = SignalRecord(
            batch_id=self.batch_b.batch_id,
            proposal=self.proposal_nvda_b,
            recorded_at=self.completed_b,
            expires_at="2026-08-25T12:00:00+00:00",
        )

        self.signal_book = SignalBook(
            batches=(self.batch_a, self.batch_b),
            records=(self.record_aapl_a, self.record_msft_a, self.record_aapl_b, self.record_nvda_b),
        )

        self.snapshot = AccountSnapshot(
            broker="toss",
            account_id="acc123",
            captured_at=self.snapshot_at,
            base_currency="USD",
            cash_value=10000.0,
            positions=(),
            open_order_ids=(),
        )

    def test_constructor_uses_exact_active_batch_only(self):
        constructor = PortfolioConstructor()
        # Construct portfolio targeting active_batch_a
        proposal = constructor.construct_optimized(
            run_id="run_1",
            source_version="v1",
            stage="live",
            as_of_at=self.decision_at,
            active_batch_id=self.batch_a.batch_id,
            signal_book=self.signal_book,
            snapshot=self.snapshot,
            expected_account_id="acc123",
            tracked_symbols=["AAPL", "MSFT", "NVDA"],
        )

        # Verify weights contain ONLY AAPL and MSFT from Batch A, NOT NVDA from Batch B
        self.assertIn("AAPL", proposal.weights)
        self.assertIn("MSFT", proposal.weights)
        self.assertNotIn("NVDA", proposal.weights)

        # Optimizer is bounded by the exact Batch A records, and never receives Batch B's NVDA.
        self.assertLessEqual(proposal.weights["AAPL"], 0.1)
        self.assertLessEqual(proposal.weights["MSFT"], 0.1)
        self.assertGreaterEqual(proposal.weights[CASH_SYMBOL], 0.8)

        # Verify proposal metadata
        self.assertEqual(proposal.model_artifact_id, "model_artifact_a")
        self.assertEqual(proposal.metadata["active_batch_id"], self.batch_a.batch_id)
        self.assertEqual(proposal.metadata["signal_model_artifact_ids"], ["model_artifact_a"])

    def test_execution_intent_rejects_unpromoted_model_artifact(self):
        # Proposal created with model_artifact_b (which is NOT promoted to live)
        constructor = PortfolioConstructor()
        proposal_b = constructor.construct_optimized(
            run_id="run_b",
            source_version="v1",
            stage="live",
            as_of_at=self.decision_at,
            active_batch_id=self.batch_b.batch_id,
            signal_book=self.signal_book,
            snapshot=self.snapshot,
            expected_account_id="acc123",
            tracked_symbols=["AAPL", "MSFT", "NVDA"],
        )

        decision = RiskDecision(
            risk_decision_id="risk_00000000000000000000000b",
            proposal_id=proposal_b.proposal_id,
            policy_key="test-policy",
            policy_version=1,
            policy_hash="0" * 64,
            input_hash="0" * 64,
            is_approved=True,
            approved_weights=proposal_b.weights,
            violations=(),
            adjustments=(),
            decided_at=self.decision_at,
        )

        # Only model_artifact_a is promoted
        repo = FakeDecisionRepository(
            proposals={proposal_b.proposal_id: {
                **proposal_b.to_dict(),
                "account_snapshot_id": "execution_snapshot_1",
            }},
            risk_decisions={decision.risk_decision_id: decision.to_dict()},
            promoted_artifacts={("model_artifact_a", "live")},
        )
        exec_repo = FakeExecutionRepository()

        with self.assertRaises(RuntimeError) as ctx:
            create_execution_intent(
                risk_decision_id=decision.risk_decision_id,
                execution_mode="live",
                confirmation=decision.risk_decision_id,
                now=self.decision_at,
                repository=repo,
                execution_repository=exec_repo,
            )
        self.assertIn("has not received manual promotion to live", str(ctx.exception))

    def test_execution_intent_rejects_mismatched_signal_artifacts_in_metadata(self):
        # Craft a proposal where model_artifact_id is 'model_artifact_a' (promoted)
        # but signal_model_artifact_ids contains 'model_artifact_b' (unpromoted)
        corrupted_proposal = PortfolioProposal.create(
            run_id="run_corrupt",
            source_type="llm",
            source_version="v1",
            stage="live",
            as_of_at=self.decision_at,
            weights={"AAPL": 0.5, CASH_SYMBOL: 0.5},
            confidence=0.9,
            reasoning=("Corrupted",),
            model_artifact_id="model_artifact_a",
            metadata={
                "coverage": "full_portfolio",
                "execution_eligible": True,
                "snapshot_captured_at": self.snapshot_at,
                "signal_model_artifact_ids": ["model_artifact_a", "model_artifact_b"],
            },
        )

        decision = RiskDecision(
            risk_decision_id="risk_00000000000000000000000c",
            proposal_id=corrupted_proposal.proposal_id,
            policy_key="test-policy",
            policy_version=1,
            policy_hash="0" * 64,
            input_hash="0" * 64,
            is_approved=True,
            approved_weights=corrupted_proposal.weights,
            violations=(),
            adjustments=(),
            decided_at=self.decision_at,
        )

        repo = FakeDecisionRepository(
            proposals={corrupted_proposal.proposal_id: {
                **corrupted_proposal.to_dict(),
                "account_snapshot_id": "execution_snapshot_1",
            }},
            risk_decisions={decision.risk_decision_id: decision.to_dict()},
            promoted_artifacts={("model_artifact_a", "live")},
        )
        exec_repo = FakeExecutionRepository()

        with self.assertRaises(RuntimeError) as ctx:
            create_execution_intent(
                risk_decision_id=decision.risk_decision_id,
                execution_mode="live",
                confirmation=decision.risk_decision_id,
                now=self.decision_at,
                repository=repo,
                execution_repository=exec_repo,
            )
        self.assertIn("mismatched model artifacts", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
