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

    def test_ridge_penalty_does_not_depend_on_feature_units(self):
        rng = np.random.default_rng(5)
        x = rng.normal(size=(40, 3))
        y = x[:, 0] * 0.02 - x[:, 1] * 0.01 + rng.normal(0.0, 0.005, size=40)
        rescaled = x.copy()
        rescaled[:, 2] *= 1000.0  # 같은 정보를 다른 단위로 적은 feature
        periods = dict(
            feature_version="pit-v1",
            train_period=("2025-01-01T00:00:00+00:00", "2025-06-01T00:00:00+00:00"),
            validation_period=("2025-06-01T00:00:00+00:00", "2025-08-01T00:00:00+00:00"),
            oos_period=("2025-08-01T00:00:00+00:00", "2025-10-01T00:00:00+00:00"),
            parameters={"alpha": 5.0},
        )

        def fit(features):
            return fit_baseline(
                "ridge",
                train_features=features[:30], train_labels=y[:30],
                validation_features=features[30:35], validation_labels=y[30:35],
                oos_features=features[35:], oos_labels=y[35:], **periods,
            )

        original_model, _ = fit(x)
        rescaled_model, artifact = fit(rescaled)
        np.testing.assert_allclose(
            original_model.predict(x[35:]), rescaled_model.predict(rescaled[35:]), rtol=1e-9,
        )
        self.assertEqual(artifact.parameters["feature_scaling"], "train_zscore")


if __name__ == "__main__":
    unittest.main()
