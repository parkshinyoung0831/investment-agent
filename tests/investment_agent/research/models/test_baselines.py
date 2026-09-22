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
            oos_features=x[8:], oos_labels=y[8:],
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


class RankCorrelationTieTest(unittest.TestCase):
    """상수 예측의 순위 상관은 표본 행 순서가 아니라 0이다."""

    def _oos_rank_correlation(self, labels):
        """naive는 train 평균 하나만 예측하므로 OOS 예측이 전부 같은 값이다."""
        x = np.arange(len(labels) * 2, dtype=float).reshape(len(labels), 2) / 10
        y = np.asarray(labels, dtype=float)
        _, artifact = fit_baseline(
            "naive",
            train_features=x, train_labels=y,
            validation_features=x, validation_labels=y,
            oos_features=x, oos_labels=y,
            train_period=("2025-01-01T00:00:00+00:00", "2025-06-01T00:00:00+00:00"),
            validation_period=("2025-06-01T00:00:00+00:00", "2025-08-01T00:00:00+00:00"),
            oos_period=("2025-08-01T00:00:00+00:00", "2025-10-01T00:00:00+00:00"),
            random_seed=3,
        )
        return artifact.out_of_sample.rank_correlation

    def test_constant_prediction_has_no_rank_skill_whatever_the_row_order(self):
        ascending = [-0.05, -0.01, 0.0, 0.02, 0.07]
        self.assertEqual(self._oos_rank_correlation(ascending), 0.0)
        self.assertEqual(self._oos_rank_correlation(list(reversed(ascending))), 0.0)
        self.assertEqual(self._oos_rank_correlation([0.02, -0.05, 0.07, 0.0, -0.01]), 0.0)

    def test_tied_labels_do_not_change_the_correlation_with_their_order(self):
        """동점 label을 어떤 순서로 넣어도 같은 값이어야 한다."""
        from investment_agent.research.models.baselines import _rank_correlation

        actual = np.array([0.0, 0.1, 0.0, 0.2, 0.0])
        predicted = np.array([0.5, 0.1, 0.4, 0.2, 0.3])
        order = [0, 1, 3, 4, 2]
        self.assertAlmostEqual(
            _rank_correlation(actual, predicted),
            _rank_correlation(actual[order], predicted[order]),
        )


if __name__ == "__main__":
    unittest.main()
