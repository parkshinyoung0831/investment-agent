from __future__ import annotations

import unittest

import numpy as np

from investment_agent.research.rl.environment import FeatureDataset, RewardConfig
from investment_agent.research.rl.experiment import _evaluate


class _AlwaysCash:
    def predict(self, observation, deterministic=True):
        _ = observation, deterministic
        return np.array([-10.0, 10.0]), None


class PPOExperimentContractTest(unittest.TestCase):
    def test_oos_evaluation_uses_every_period_and_reports_costs(self):
        dataset = FeatureDataset(
            symbols=("AAPL",), feature_names=("momentum",),
            as_of_values=("2026-01-02", "2026-01-05"),
            features=np.array([[[0.1]], [[0.2]]]),
            forward_returns=np.array([[0.05], [-0.02]]),
            benchmark_forward_returns=np.array([0.01, 0.01]),
            availability=np.array([[True], [True]]),
            feature_version="v1",
        )
        result = _evaluate(_AlwaysCash(), dataset, RewardConfig())
        self.assertEqual(result.periods, 2)
        self.assertAlmostEqual(result.total_return, 0.0, places=6)
        self.assertAlmostEqual(result.benchmark_return, 0.0201, places=6)
        self.assertGreaterEqual(result.transaction_cost, 0.0)


if __name__ == "__main__":
    unittest.main()
