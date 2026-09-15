"""RL 정책은 ALPHA 분석 경로에 섞이지 않는다. RL은 오프라인 연구·평가로만 남는다."""
from __future__ import annotations

import inspect
import unittest

from investment_agent.trading.decision import analysis as module


class AnalysisPathTest(unittest.TestCase):
    def test_analysis_has_no_rl_or_portfolio_step(self):
        """분석은 논지만 남긴다. RL 목표비중·포트폴리오 제안을 다시 만들지 않게 한다."""
        source = inspect.getsource(module)
        for forbidden in ("compute_rl_target_weights", "blend_proposals", "SignalBlender",
                          "save_portfolio_proposal", "DeterministicRiskGate", "RiskAwareOptimizer"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
