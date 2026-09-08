from __future__ import annotations

import unittest

import numpy as np

from investment_agent.research.models.baselines import fit_baseline


class MLBaselineTest(unittest.TestCase):
    def test_ridge_artifact_is_reproducible(self):
        x = np.arange(30, dtype=float).reshape(10, 3) / 10
        y = x[:, 0] * 0.1 - x[:, 1] * 0.02
        kwargs = dict(
            train_features=x[:6], train_labels=y[:6],
            validation_features=x[6:8], validation_labels=y[6:8],
            oos_features=x[8:], oos_labels=y[8:], feature_version="pit-v1",
            train_period=("2025-01-01T00:00:00+00:00", "2025-06-01T00:00:00+00:00"),
            validation_period=("2025-06-01T00:00:00+00:00", "2025-08-01T00:00:00+00:00"),
            oos_period=("2025-08-01T00:00:00+00:00", "2025-10-01T00:00:00+00:00"),
            random_seed=11,
        )
        _, first = fit_baseline("ridge", **kwargs)
        _, second = fit_baseline("ridge", **kwargs)
        self.assertEqual(first.artifact_hash, second.artifact_hash)
        row = first.to_db_record(artifact_uri="artifacts/ml/ridge.json")
        self.assertEqual(row["algorithm"], "ridge")
        self.assertEqual(row["params"]["horizon_days"], 5)
        self.assertEqual(row["sha256"], first.artifact_hash)
        self.assertEqual(first.dataset_hash, second.dataset_hash)


if __name__ == "__main__":
    unittest.main()
