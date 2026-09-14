"""원본 판단과 실제 소비할 융합 신호의 출처를 분리한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from investment_agent.trading.decision import portfolio_shadow as module
from investment_agent.trading.portfolio.contracts import SecurityProposal
from investment_agent.research.rl.serving import RlBlendOutcome


class EffectiveSignalsTest(unittest.TestCase):
    def test_applied_blend_has_distinct_promotion_identity_and_preserves_original(self):
        now = datetime.now(timezone.utc)
        original = SecurityProposal('AAPL', now.isoformat(), 'open', .6, .8, .05, .1, ('근거',), ())
        repository = Mock()
        outcome = RlBlendOutcome(available=True, applied=True, policy_artifact_id='ppo-hash', dsr_probability=.99, weights={'AAPL': .2})
        with patch.object(module, 'compute_rl_blend', return_value=outcome):
            proposals, artifact = module._effective_proposals(repository, [original], as_of=now, model_artifact_id='llm')
        self.assertEqual(original.expected_excess_return, .05)
        self.assertNotEqual(artifact, 'llm')
        self.assertNotEqual(proposals[0].expected_excess_return, original.expected_excess_return)
        self.assertEqual(repository.save_model_artifact.call_args.args[0]['params']['rl_artifact_id'], 'ppo-hash')

    def test_unavailable_policy_keeps_original_artifact_and_proposal(self):
        repository = Mock()
        with patch.object(module, 'compute_rl_blend', return_value=RlBlendOutcome(False, False, reason='missing')):
            proposals, artifact = module._effective_proposals(repository, [], as_of=datetime.now(timezone.utc), model_artifact_id='llm')
        self.assertEqual((proposals, artifact), ([], 'llm'))
        repository.save_model_artifact.assert_not_called()
