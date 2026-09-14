"""RL 정책은 판단 신호를 바꾸지 않고 challenger 목표비중으로만 남는다."""
from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from investment_agent.research.rl.serving import RlPolicyOutcome
from investment_agent.trading.decision import portfolio_shadow as module


class RlChallengerTest(unittest.TestCase):
    def test_available_policy_only_reports_weights(self):
        now = datetime.now(timezone.utc)
        repository = Mock()
        outcome = RlPolicyOutcome(available=True, policy_artifact_id="ppo-hash", dsr_probability=.99,
                                  weights={"AAPL": .2})
        with patch.object(module, "compute_rl_target_weights", return_value=outcome):
            result = module._rl_challenger(repository, [], as_of=now)
        self.assertEqual(result.weights, {"AAPL": .2})
        repository.save_model_artifact.assert_not_called()

    def test_signal_path_has_no_rl_blending_step(self):
        """RL 목표비중을 기대수익으로 되돌리는 경로가 다시 생기지 않게 한다."""
        source = inspect.getsource(module)
        self.assertNotIn("blend_proposals", source)
        self.assertNotIn("SignalBlender", source)


if __name__ == "__main__":
    unittest.main()
