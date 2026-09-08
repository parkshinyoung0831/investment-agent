from __future__ import annotations

import unittest

import numpy as np

from investment_agent.research.rl.environment import (
    FeatureDataset,
    RewardConfig,
    WeightEnvironmentCore,
    action_to_weights,
)
from investment_agent.research.training.splits import make_walk_forward_splits


def dataset() -> FeatureDataset:
    return FeatureDataset(
        symbols=("AAPL", "MSFT"),
        feature_names=("momentum",),
        as_of_values=("2026-01-01", "2026-01-02", "2026-01-03"),
        features=np.array([[[1.0], [2.0]], [[1.1], [2.1]], [[1.2], [2.2]]]),
        forward_returns=np.array([[0.01, 0.02], [-0.01, 0.01], [0.0, 0.0]]),
        benchmark_forward_returns=np.array([0.005, 0.0, 0.0]),
        availability=np.array([[True, False], [True, True], [True, True]]),
        feature_version="v1",
    )


class WeightEnvironmentTest(unittest.TestCase):
    def test_unavailable_asset_gets_zero_weight(self):
        weights = action_to_weights([0.0, 10.0, 0.0], np.array([True, False]))
        self.assertEqual(weights[1], 0.0)
        self.assertAlmostEqual(float(weights.sum()), 1.0)

    def test_state_contains_features_mask_and_current_weights(self):
        core = WeightEnvironmentCore(dataset(), RewardConfig())
        observation = core.reset()
        self.assertEqual(len(observation), core.observation_size)
        _, reward, done, info = core.step([1.0, 1.0, 0.0])
        self.assertFalse(done)
        self.assertTrue(np.isfinite(reward))
        self.assertIn("transaction_cost", info)
        self.assertAlmostEqual(sum(info["weights"].values()), 1.0)

    def test_walk_forward_has_embargo_gaps(self):
        splits = make_walk_forward_splits(
            list(range(30)), train_size=10, validation_size=4,
            out_of_sample_size=3, embargo_size=2,
        )
        self.assertTrue(splits)
        first = splits[0]
        self.assertEqual(first.train, (0, 10))
        self.assertEqual(first.validation, (12, 16))
        self.assertEqual(first.out_of_sample, (18, 21))

    def test_reward_deducts_turnover_cost_from_realized_return(self):
        config = RewardConfig(
            alpha_weight=0.0,
            drawdown_penalty=0.0,
            volatility_penalty=0.0,
            turnover_penalty=0.0,
            concentration_penalty=0.0,
            transaction_cost_rate=0.01,
        )
        core = WeightEnvironmentCore(dataset(), config)
        core.reset()
        # 한 종목에 전부 몰아넣는 action이지만 종목 상한 10%가 걸리므로 실제 목표는
        # 위험자산 10% + 현금 90%다. 전량 현금에서 출발하니 turnover는 0.10이다.
        _, reward, _, info = core.step([1000.0, -1000.0, -1000.0])
        self.assertAlmostEqual(info["weights"]["AAPL"], 0.10)
        self.assertAlmostEqual(info["weights"]["CASH"], 0.90)
        self.assertAlmostEqual(info["turnover"], 0.10)
        self.assertAlmostEqual(info["transaction_cost"], 0.001)
        self.assertAlmostEqual(
            info["net_return"],
            info["gross_return"] - info["transaction_cost"],
        )
        self.assertAlmostEqual(reward, info["net_return"])

    def test_every_labeled_period_is_consumed_before_terminal_state(self):
        core = WeightEnvironmentCore(dataset())
        done_values = []
        for _ in range(3):
            observation, _, done, _ = core.step([0.0, 0.0, 0.0])
            done_values.append(done)
            self.assertEqual(len(observation), core.observation_size)
        self.assertEqual(done_values, [False, False, True])
        with self.assertRaisesRegex(RuntimeError, "already complete"):
            core.step([0.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
