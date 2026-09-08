from __future__ import annotations

import unittest
from dataclasses import asdict

from investment_agent.reporting.services.investment import (
    build_fusion_policy_read_model,
    build_optimizer_policy_read_model,
    build_ranker_policy_read_model,
    build_risk_policy_read_model,
)
from investment_agent.trading.portfolio.optimizer import OptimizerPolicy
from investment_agent.trading.risk.gate import PortfolioRiskPolicy
from investment_agent.trading.decision.fusion import DEFAULT_COMPONENT_WEIGHTS
from investment_agent.trading.decision.fast_ranker import FastRankerPolicy


class InvestmentPolicySnapshotTest(unittest.TestCase):
    def test_fusion_policy_read_model_preserves_current_defaults(self) -> None:
        self.assertEqual(
            {
                "version": "signal-fusion-v1",
                "component_weights": dict(DEFAULT_COMPONENT_WEIGHTS),
                "rule": "확신도로 가중하고 모델 간 방향 차이는 불확실성으로 보존",
            },
            build_fusion_policy_read_model(),
        )

    def test_optimizer_policy_read_model_preserves_current_defaults(self) -> None:
        self.assertEqual(
            asdict(OptimizerPolicy()),
            build_optimizer_policy_read_model(),
        )

    def test_ranker_policy_read_model_preserves_current_defaults(self) -> None:
        policy = FastRankerPolicy()
        self.assertEqual(
            {
                "version": policy.version,
                "baseline_weight": policy.baseline_weight,
                "numeric_weight": policy.numeric_weight,
                "max_candidates": policy.max_candidates,
                "domain_weights": dict(policy.domain_weights),
            },
            build_ranker_policy_read_model(),
        )

    def test_risk_policy_read_model_preserves_current_hard_limits(self) -> None:
        self.assertEqual(
            PortfolioRiskPolicy().to_config(),
            build_risk_policy_read_model(),
        )


if __name__ == "__main__":
    unittest.main()
