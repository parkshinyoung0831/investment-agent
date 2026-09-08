from __future__ import annotations

import unittest

from investment_agent.trading.portfolio.contracts import SecurityProposal
from investment_agent.trading.portfolio.optimizer import (
    ExpectedReturnSignal,
    OptimizerPolicy,
    RiskAwareOptimizer,
)
from investment_agent.trading.portfolio.proposals import from_optimized_security_proposals


def _proposal(target: float) -> SecurityProposal:
    return SecurityProposal(
        ticker="AAPL", as_of_at="2026-08-20T22:00:00+00:00", signal="open",
        probability_up=0.7, confidence=0.8, expected_excess_return=0.04,
        target_weight=target, reasoning=("evidence",), evidence_ids=("EV-1",),
    )


class OptimizerTest(unittest.TestCase):
    def test_correlated_assets_receive_a_larger_variance_penalty(self):
        signals = (
            ExpectedReturnSignal("AAPL", 0.04, 1.0, 0.1, 5, "test", "2026-08-20T22:00:00+00:00", "v1"),
            ExpectedReturnSignal("MSFT", 0.04, 1.0, 0.1, 5, "test", "2026-08-20T22:00:00+00:00", "v1"),
        )
        policy = OptimizerPolicy(risk_aversion=100.0, max_turnover=1.0, turnover_penalty=0.0)
        optimizer = RiskAwareOptimizer(policy)
        independent = optimizer.optimize(
            signals,
            current_weights={"CASH": 1.0},
            covariance=((0.01, 0.0), (0.0, 0.01)),
        )
        correlated = optimizer.optimize(
            signals,
            current_weights={"CASH": 1.0},
            covariance=((0.01, 0.009), (0.009, 0.01)),
        )
        self.assertLess(
            correlated.weights["AAPL"] + correlated.weights["MSFT"],
            independent.weights["AAPL"] + independent.weights["MSFT"],
        )
        self.assertGreater(correlated.estimated_variance, 0.0)
        self.assertAlmostEqual(
            correlated.objective_value,
            correlated.expected_return_component - correlated.risk_penalty - correlated.turnover_penalty,
        )

    def test_llm_target_weight_is_not_an_optimizer_input(self):
        policy = OptimizerPolicy(max_turnover=1.0, min_cash_weight=0.1)
        left = from_optimized_security_proposals(
            [_proposal(0.01)], run_id="run-1", source_version="ta-v1",
            current_weights={"CASH": 1.0}, optimizer_policy=policy,
        )
        right = from_optimized_security_proposals(
            [_proposal(0.99)], run_id="run-1", source_version="ta-v1",
            current_weights={"CASH": 1.0}, optimizer_policy=policy,
        )
        self.assertEqual(left.weights, right.weights)
        self.assertFalse(left.metadata["llm_target_weight_used"])
        self.assertLessEqual(left.weights["AAPL"], policy.max_symbol_weight + 1e-8)
        self.assertGreaterEqual(left.weights["CASH"], policy.min_cash_weight - 1e-8)


if __name__ == "__main__":
    unittest.main()
