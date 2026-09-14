"""저장한 ML artifact가 학습 때와 같은 예측기로 되살아나는지."""
from __future__ import annotations

import unittest

import numpy as np

from investment_agent.research.ml_inference import load_model
from investment_agent.research.models.baselines import fit_baseline
from investment_agent.trading.contracts import ContractError

_AS_OF = "2026-08-20T22:00:00+00:00"
_NAMES = ("momentum", "value", "quality")


def _fitted(kind: str = "ridge", *, rank_correlation=None, direction_accuracy=None):
    rng = np.random.default_rng(11)
    x = rng.normal(size=(90, len(_NAMES)))
    y = x @ np.array([0.02, -0.01, 0.005]) + rng.normal(scale=0.001, size=90)
    model, artifact = fit_baseline(
        kind,
        train_features=x[:50], train_labels=y[:50],
        validation_features=x[50:70], validation_labels=y[50:70],
        oos_features=x[70:], oos_labels=y[70:],
        feature_version="v3", horizon_days=5,
        train_period=["2026-01-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00"],
        validation_period=["2026-03-02T00:00:00+00:00", "2026-04-01T00:00:00+00:00"],
        oos_period=["2026-04-02T00:00:00+00:00", "2026-05-01T00:00:00+00:00"],
        parameters={"alpha": 1.0} if kind == "ridge" else ({"n_estimators": 20} if kind in ("lightgbm", "xgboost") else {}),
    )
    record = artifact.to_record()
    if rank_correlation is not None:
        record["out_of_sample"]["rank_correlation"] = rank_correlation
    if direction_accuracy is not None:
        record["out_of_sample"]["direction_accuracy"] = direction_accuracy
    return model, {
        "artifact": record,
        "model_state": model.state(),
        "feature_names": list(_NAMES),
    }


def _artifact(kind: str = "ridge", **kwargs):
    return _fitted(kind, **kwargs)[1]


def _rows(count: int = 3):
    return [
        {"momentum": 0.1 * (i + 1), "value": -0.05 * i, "quality": 0.2}
        for i in range(count)
    ]


class LoadModelTest(unittest.TestCase):
    def test_ridge_round_trips_through_the_saved_state(self):
        payload = _artifact("ridge")
        model = load_model(payload)
        self.assertEqual(model.model_kind, "ridge")
        self.assertEqual(model.feature_names, _NAMES)
        self.assertEqual(model.horizon_days, 5)

    def test_naive_round_trips(self):
        model = load_model(_artifact("naive"))
        predictions = model.predict(np.zeros((4, len(_NAMES))))
        self.assertEqual(len(set(predictions.tolist())), 1)

    def test_boosted_models_round_trip_to_identical_predictions(self):
        """booster 원문을 저장해야 학습 때와 같은 예측을 다시 만든다."""
        rows = np.asarray([[0.1, -0.2, 0.3], [0.5, 0.1, -0.4], [-0.3, 0.2, 0.0]])
        for kind in ("lightgbm", "xgboost"):
            with self.subTest(kind=kind):
                trained, payload = _fitted(kind)
                reloaded = load_model(payload)
                np.testing.assert_allclose(reloaded.predict(rows), trained.predict(rows), rtol=1e-6, atol=1e-9)

    def test_boosted_artifact_without_a_booster_is_refused(self):
        """중요도 목록만 남은 옛 artifact는 같은 예측을 만들 수 없다."""
        _, payload = _fitted("lightgbm")
        payload["model_state"].pop("booster")
        with self.assertRaises(ContractError):
            load_model(payload)

    def test_boosted_training_is_reproducible(self):
        self.assertEqual(_fitted("lightgbm")[1]["artifact"]["artifact_hash"],
                         _fitted("lightgbm")[1]["artifact"]["artifact_hash"])

    def test_coefficient_length_mismatch_is_refused(self):
        payload = _artifact("ridge")
        payload["model_state"]["coefficients"] = [1.0]
        with self.assertRaises(ContractError):
            load_model(payload)


class ConfidenceFromEvidenceTest(unittest.TestCase):
    """신뢰도를 상수로 두지 않고 측정된 OOS 성능에서 가져온다."""

    def test_negative_rank_correlation_yields_zero_confidence(self):
        model = load_model(_artifact("ridge", rank_correlation=-0.3))
        self.assertEqual(model.confidence, 0.0)

    def test_confidence_is_capped_so_one_model_cannot_dominate(self):
        model = load_model(_artifact("ridge", rank_correlation=0.99))
        self.assertEqual(model.confidence, 0.8)

    def test_probability_up_follows_measured_direction_accuracy(self):
        model = load_model(_artifact("ridge", direction_accuracy=0.62))
        self.assertAlmostEqual(model.probability_up(0.01), 0.62)
        self.assertAlmostEqual(model.probability_up(-0.01), 0.38)
        self.assertEqual(model.probability_up(0.0), 0.5)



if __name__ == "__main__":
    unittest.main()
