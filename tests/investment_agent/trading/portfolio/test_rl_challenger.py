"""RL baseline 추론 비중을 실행 권한 없는 challenger 제안으로 감싸는 계약을 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.trading.portfolio.rl_challenger import rl_challenger_proposal

WEIGHTS = {"AAPL": 0.4, "CASH": 0.6}


def _proposal(**overrides):
    values = dict(
        run_id="run-rl",
        stage="shadow",
        as_of_at="2026-02-01T21:00:00+00:00",
        weights=WEIGHTS,
        source_version="linear-ridge-policy-v1",
        model_artifact_id="artifact-1",
        input_hash="b" * 64,
        membership_hash="a" * 64,
    )
    values.update(overrides)
    return rl_challenger_proposal(**values)


class RlChallengerProposalTest(unittest.TestCase):
    def test_proposal_never_carries_execution_authority(self) -> None:
        proposal = _proposal()
        self.assertFalse(proposal.metadata["execution_eligible"])
        self.assertEqual("partial_universe", proposal.metadata["coverage"])
        self.assertEqual("rl_baseline_challenger", proposal.metadata["purpose"])

    def test_proposal_records_source_and_inputs(self) -> None:
        proposal = _proposal()
        self.assertEqual("rl", proposal.source_type)
        self.assertEqual("shadow", proposal.stage)
        self.assertEqual("artifact-1", proposal.model_artifact_id)
        self.assertEqual("b" * 64, proposal.metadata["inference_input_hash"])
        self.assertEqual("a" * 64, proposal.metadata["membership_hash"])
        self.assertEqual({"AAPL": 0.4, "CASH": 0.6}, dict(proposal.weights))

    def test_identity_is_stable_for_identical_inputs(self) -> None:
        self.assertEqual(_proposal().proposal_id, _proposal().proposal_id)
        self.assertNotEqual(_proposal().proposal_id, _proposal(run_id="run-other").proposal_id)


if __name__ == "__main__":
    unittest.main()
