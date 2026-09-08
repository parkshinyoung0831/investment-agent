"""RL 학습 비중 공간이 실제 실행 한도와 어긋나지 않는지 고정한다."""
from __future__ import annotations

import unittest

import numpy as np

from investment_agent.trading.portfolio.optimizer import OptimizerPolicy
from investment_agent.trading.risk.gate import PortfolioRiskPolicy
from investment_agent.research.rl.environment import (
    FeatureDataset,
    RewardConfig,
    WeightConstraints,
    WeightEnvironmentCore,
    action_to_weights,
)


def _dataset(symbols: tuple[str, ...], *, periods: int = 2) -> FeatureDataset:
    count = len(symbols)
    return FeatureDataset(
        symbols=symbols,
        feature_names=("momentum",),
        as_of_values=tuple(f"2026-0{index + 1}-01T21:00:00+00:00" for index in range(periods)),
        features=np.zeros((periods, count, 1)),
        forward_returns=np.full((periods, count), 0.10),
        benchmark_forward_returns=np.zeros(periods),
        availability=np.ones((periods, count), dtype=bool),
        feature_version="rl-v1",
    )


class ConstraintSourceTest(unittest.TestCase):
    """RL 한도가 optimizer/RiskGate보다 느슨해지면 여기서 잡는다."""

    def test_defaults_track_the_real_policies(self):
        constraints = WeightConstraints.from_policies()
        optimizer = OptimizerPolicy()
        risk = PortfolioRiskPolicy()
        self.assertLessEqual(constraints.max_symbol_weight, optimizer.max_symbol_weight)
        self.assertLessEqual(constraints.max_symbol_weight, risk.max_symbol_weight)
        self.assertGreaterEqual(constraints.min_cash_weight, optimizer.min_cash_weight)
        self.assertGreaterEqual(constraints.min_cash_weight, risk.min_cash_weight)
        self.assertEqual(constraints.max_positions, risk.max_positions)
        self.assertEqual(constraints.min_position_weight, risk.min_position_weight)


class ActionProjectionTest(unittest.TestCase):
    def test_all_in_action_is_capped_at_the_symbol_limit(self):
        availability = np.ones(4, dtype=bool)
        weights = action_to_weights([50.0, -50.0, -50.0, -50.0, -50.0], availability)
        self.assertAlmostEqual(float(weights.sum()), 1.0)
        self.assertLessEqual(float(weights[:-1].max()), 0.10 + 1e-9)

    def test_cash_never_falls_below_the_minimum(self):
        availability = np.ones(40, dtype=bool)
        # 40종목 × 10% = 400%를 요구해도 현금 하한이 남아야 한다.
        weights = action_to_weights(np.zeros(41), availability)
        self.assertGreaterEqual(float(weights[-1]), 0.05 - 1e-9)
        self.assertAlmostEqual(float(weights.sum()), 1.0)

    def test_min_cash_is_a_floor_not_a_target(self):
        """거의 전부 현금을 원한 policy를 위험자산 95%로 뒤집으면 안 된다."""
        availability = np.ones(2, dtype=bool)
        weights = action_to_weights([-10.0, -10.0, 10.0], availability)
        self.assertGreater(float(weights[-1]), 0.95)
        self.assertLess(float(weights[:-1].sum()), 0.05)

    def test_position_count_never_exceeds_the_limit(self):
        availability = np.ones(60, dtype=bool)
        weights = action_to_weights(np.linspace(-1.0, 1.0, 61), availability)
        self.assertLessEqual(int(np.count_nonzero(weights[:-1])), 25)
        self.assertAlmostEqual(float(weights.sum()), 1.0)

    def test_unavailable_symbols_stay_at_zero(self):
        availability = np.array([True, False, True])
        weights = action_to_weights([5.0, 9.0, 1.0, -3.0], availability)
        self.assertEqual(float(weights[1]), 0.0)
        self.assertAlmostEqual(float(weights.sum()), 1.0)

    def test_weights_remain_long_only_and_sum_to_one(self):
        availability = np.ones(6, dtype=bool)
        for logits in ([-9.0] * 7, [9.0] * 7, list(np.linspace(-4.0, 4.0, 7))):
            weights = action_to_weights(logits, availability)
            self.assertTrue((weights >= -1e-12).all())
            self.assertAlmostEqual(float(weights.sum()), 1.0)

    def test_looser_constraints_are_honoured_when_passed_explicitly(self):
        availability = np.ones(2, dtype=bool)
        loose = WeightConstraints(
            max_symbol_weight=0.50, min_cash_weight=0.0,
            max_positions=25, min_position_weight=0.0,
        )
        weights = action_to_weights([1.0, 1.0, -50.0], availability, constraints=loose)
        self.assertAlmostEqual(float(weights[0]), 0.50)
        self.assertAlmostEqual(float(weights[1]), 0.50)


class WeightDriftTest(unittest.TestCase):
    """목표를 그대로 이월하면 리밸런싱이 공짜가 되어 회전율이 과소평가된다."""

    def test_carried_weights_reflect_price_moves_not_the_target(self):
        core = WeightEnvironmentCore(
            _dataset(("AAA", "BBB")),
            RewardConfig(transaction_cost_rate=0.0),
        )
        core.reset()
        _, _, _, info = core.step([5.0, -5.0, 0.0])
        target_aaa = info["weights"]["AAA"]
        carried_aaa = float(core.current_weights[0])
        # AAA가 +10%였으므로 다음 구간 시작 비중은 목표보다 커져 있어야 한다.
        self.assertGreater(carried_aaa, target_aaa)
        self.assertAlmostEqual(float(core.current_weights.sum()), 1.0)
        self.assertAlmostEqual(carried_aaa, info["weights_after_drift"]["AAA"])

    def test_holding_the_same_target_still_costs_turnover_after_drift(self):
        core = WeightEnvironmentCore(
            _dataset(("AAA", "BBB")),
            RewardConfig(transaction_cost_rate=0.001),
        )
        core.reset()
        action = [5.0, -5.0, 0.0]
        core.step(action)
        _, _, _, second = core.step(action)
        # 같은 목표를 유지해도 그동안 비중이 흘렀으므로 되돌리는 비용이 든다.
        self.assertGreater(second["turnover"], 0.0)
        self.assertGreater(second["transaction_cost"], 0.0)


if __name__ == "__main__":
    unittest.main()
