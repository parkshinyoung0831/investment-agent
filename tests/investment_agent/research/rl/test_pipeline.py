from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.research.rl.baseline import load_baseline_policy
from investment_agent.research.rl.environment import RewardConfig
from investment_agent.research.rl.pipeline import run_baseline_walk_forward
from investment_agent.research.training.splits import make_purged_walk_forward_splits
from tests.investment_agent.research.rl.fixtures import historical_training_set


class WalkForwardPipelineTest(unittest.TestCase):
    def test_train_validation_test_run_is_reproducible_and_durable(self):
        _, training = historical_training_set(14)
        splits = make_purged_walk_forward_splits(
            training.dataset.as_of_values,
            training.forward_end_values,
            train_size=6,
            validation_size=2,
            test_size=2,
            embargo_size=1,
        )
        reward = RewardConfig(transaction_cost_rate=0.002, turnover_penalty=0.1)
        with tempfile.TemporaryDirectory() as directory:
            first = run_baseline_walk_forward(
                training,
                splits,
                seed=17,
                reward_config=reward,
                artifact_dir=Path(directory),
            )
            repeated = run_baseline_walk_forward(
                training,
                splits,
                seed=17,
                reward_config=reward,
            )
            self.assertEqual(first.run_hash, repeated.run_hash)
            self.assertEqual(len(first.windows), len(splits))
            for window in first.windows:
                self.assertEqual(window.validation.periods, 2)
                self.assertEqual(window.test.periods, 2)
                self.assertGreaterEqual(window.validation.transaction_cost, 0.0)
                self.assertGreaterEqual(window.test.turnover, 0.0)
                self.assertIsNotNone(window.artifact)
                artifact = window.artifact
                assert artifact is not None
                loaded = load_baseline_policy(
                    Path(artifact.artifact_uri),
                    expected_sha256=artifact.sha256,
                )
                self.assertEqual(loaded.artifact_id, window.model.artifact_id)


if __name__ == "__main__":
    unittest.main()
