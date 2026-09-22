from __future__ import annotations

import unittest
from dataclasses import asdict, replace

from investment_agent.reporting.services.investment import (
    build_alpha_policy_read_model,
    build_optimizer_policy_read_model,
    build_risk_policy_read_model,
)
from investment_agent.trading.portfolio.optimizer import OptimizerPolicy
from investment_agent.trading.risk.gate import PortfolioRiskPolicy
from investment_agent.trading.system.target import SystemPortfolioPolicy
from investment_agent.trading.decision.alpha import AlphaPolicy


class InvestmentPolicySnapshotTest(unittest.TestCase):
    def test_alpha_policy_read_model_preserves_current_defaults(self) -> None:
        self.assertEqual(
            {
                **AlphaPolicy().to_dict(),
                "rule": "factor 사전값에 champion ML을 OOS 신뢰도만큼 결합하고 TradingAgents는 거부권·소폭 조정만 적용",
            },
            build_alpha_policy_read_model(),
        )

    def test_optimizer_policy_read_model_preserves_current_defaults(self) -> None:
        self.assertEqual(
            asdict(OptimizerPolicy()),
            build_optimizer_policy_read_model(),
        )

    def _effective_policy(self):
        """System 파이프라인이 실제로 만드는 정책(`trading/system/target.py`와 같은 조립)."""
        return replace(
            PortfolioRiskPolicy(), max_cvar_95_5d=SystemPortfolioPolicy().max_cvar_95_5d,
        )

    def test_risk_policy_read_model_preserves_current_hard_limits(self) -> None:
        self.assertEqual(
            self._effective_policy().to_config(),
            build_risk_policy_read_model(),
        )

    def test_the_cvar_limit_shown_is_the_one_runs_actually_use(self) -> None:
        """맨몸 기본값은 변동성에서 유도한 값이라 어떤 실행도 쓰지 않는다."""
        shown = build_risk_policy_read_model()["cvar_95_5d_limit"]
        self.assertEqual(shown, SystemPortfolioPolicy().max_cvar_95_5d)
        self.assertNotEqual(shown, PortfolioRiskPolicy().cvar_95_5d_limit)


if __name__ == "__main__":
    unittest.main()
