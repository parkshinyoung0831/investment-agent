from __future__ import annotations

import unittest
from dataclasses import asdict

from investment_agent.reporting.services.investment import (
    build_alpha_policy_read_model,
    build_optimizer_policy_read_model,
    build_risk_policy_read_model,
)
from investment_agent.trading.portfolio.optimizer import OptimizerPolicy
from investment_agent.trading.risk.gate import PortfolioRiskPolicy
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

    def test_risk_policy_read_model_preserves_current_hard_limits(self) -> None:
        self.assertEqual(
            PortfolioRiskPolicy().to_config(),
            build_risk_policy_read_model(),
        )


if __name__ == "__main__":
    unittest.main()
