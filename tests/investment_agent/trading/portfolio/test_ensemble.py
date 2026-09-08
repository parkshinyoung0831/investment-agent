"""ML 추론과 LLM·ML·RL 앙상블 조립 계약을 고정한다."""
from __future__ import annotations

import unittest

import numpy as np

from investment_agent.trading.contracts import ContractError
from investment_agent.research.models.baselines import fit_baseline
from investment_agent.research.ml_inference import (
    HORIZON_SCALE,
    load_model,
    predict_numeric,
)
from investment_agent.trading.portfolio.contracts import PortfolioProposal
from investment_agent.trading.portfolio.ensemble import (
    collect_candidates,
    to_optimizer_signal,
    weight_disagreement,
)
from investment_agent.trading.decision.contracts import ExpectedReturnSignal
from investment_agent.trading.decision.fusion import fuse_signals

_AS_OF = "2026-08-20T22:00:00+00:00"
_NAMES = ("momentum", "value", "quality")


def _artifact(kind: str = "ridge", *, rank_correlation=None, direction_accuracy=None):
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
        parameters={"alpha": 1.0} if kind == "ridge" else {},
    )
    record = artifact.to_record()
    if rank_correlation is not None:
        record["out_of_sample"]["rank_correlation"] = rank_correlation
    if direction_accuracy is not None:
        record["out_of_sample"]["direction_accuracy"] = direction_accuracy
    return {
        "artifact": record,
        "model_state": model.state(),
        "feature_names": list(_NAMES),
    }


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

    def test_boosted_artifact_is_refused_for_live_inference(self):
        """부스팅 계열은 artifact에 복원 가능한 상태가 남지 않는다."""
        payload = _artifact("ridge")
        payload["artifact"]["model_kind"] = "lightgbm"
        with self.assertRaises(ContractError):
            load_model(payload)

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


class PredictNumericTest(unittest.TestCase):
    def _model(self, **kwargs):
        return load_model(_artifact("ridge", **kwargs))

    def test_predictions_cover_every_horizon_with_one_ratio(self):
        model = self._model()
        predictions = predict_numeric(
            model, as_of_at=_AS_OF, tickers=["AAA", "BBB", "CCC"],
            feature_rows=_rows(), feature_version="v3",
        )
        self.assertEqual(len(predictions), 3)
        first = predictions[0]
        self.assertAlmostEqual(
            first.expected_1d_return / first.expected_5d_return,
            HORIZON_SCALE[1] / HORIZON_SCALE[5],
        )

    def test_feature_version_mismatch_stops_inference(self):
        """training-serving skew는 조용히 틀린 답을 준다."""
        with self.assertRaises(ContractError):
            predict_numeric(
                self._model(), as_of_at=_AS_OF, tickers=["AAA"],
                feature_rows=_rows(1), feature_version="v2",
            )

    def test_missing_feature_column_stops_inference(self):
        rows = _rows(1)
        del rows[0]["quality"]
        with self.assertRaises(KeyError):
            predict_numeric(
                self._model(), as_of_at=_AS_OF, tickers=["AAA"],
                feature_rows=rows, feature_version="v3",
            )

    def test_evidence_ids_are_carried_through(self):
        predictions = predict_numeric(
            self._model(), as_of_at=_AS_OF, tickers=["AAA"],
            feature_rows=_rows(1), feature_version="v3",
            evidence_by_ticker={"AAA": ("EV-1", "EV-2")},
        )
        self.assertEqual(predictions[0].evidence_ids, ("EV-1", "EV-2"))


class SignalBridgeTest(unittest.TestCase):
    def _signal(self, **kwargs) -> ExpectedReturnSignal:
        payload = {
            "ticker": "AAA", "as_of_at": _AS_OF,
            "expected_1d_return": 0.002, "expected_5d_return": 0.01,
            "expected_20d_return": 0.025, "probability_up": 0.6,
            "confidence": 0.7, "uncertainty": 0.3, "preferred_horizon": "5d",
            "model_id": "signal-fusion", "version": "ensemble-v1",
            "evidence_ids": ("EV-1",),
        }
        payload.update(kwargs)
        return ExpectedReturnSignal(**payload)

    def test_uncertainty_becomes_the_optimizer_risk_score(self):
        """모델들이 엇갈릴수록 optimizer가 그 종목을 덜 담아야 한다."""
        signal = to_optimizer_signal(self._signal(uncertainty=0.42))
        self.assertEqual(signal.risk_score, 0.42)
        self.assertEqual(signal.expected_return, 0.01)
        self.assertEqual(signal.horizon_days, 5)

    def test_preferred_horizon_selects_the_matching_return(self):
        signal = to_optimizer_signal(self._signal(preferred_horizon="20d"))
        self.assertEqual(signal.expected_return, 0.025)
        self.assertEqual(signal.horizon_days, 20)

    def test_evidence_survives_the_bridge(self):
        self.assertEqual(to_optimizer_signal(self._signal()).evidence_ids, ("EV-1",))


class EnsembleCandidatesTest(unittest.TestCase):
    def _proposal(self, source: str, weights: dict) -> PortfolioProposal:
        return PortfolioProposal.create(
            run_id="run_1", source_type=source, source_version="v1",
            stage="shadow", as_of_at=_AS_OF, weights=weights, confidence=0.5,
            reasoning=("test",),
        )

    def test_two_sources_are_collected_with_their_disagreement(self):
        left = self._proposal("optimizer", {"AAA": 0.1, "CASH": 0.9})
        right = self._proposal("rl", {"BBB": 0.1, "CASH": 0.9})
        candidates = collect_candidates(
            as_of_at=_AS_OF, optimizer_proposal=left, rl_proposal=right,
        )
        self.assertEqual(len(candidates.proposals), 2)
        self.assertAlmostEqual(candidates.contributors["weight_disagreement"], 0.1)

    def test_identical_portfolios_have_zero_disagreement(self):
        weights = {"AAA": 0.1, "CASH": 0.9}
        self.assertEqual(
            weight_disagreement(self._proposal("optimizer", weights),
                                self._proposal("rl", dict(weights))),
            0.0,
        )

    def test_a_single_available_model_still_produces_candidates(self):
        candidates = collect_candidates(
            as_of_at=_AS_OF,
            optimizer_proposal=self._proposal("optimizer", {"AAA": 0.1, "CASH": 0.9}),
        )
        self.assertEqual(len(candidates.proposals), 1)
        self.assertIsNone(candidates.by_source("rl"))
        self.assertNotIn("weight_disagreement", candidates.contributors)

    def test_duplicate_source_types_are_refused(self):
        with self.assertRaises(ContractError):
            collect_candidates(
                as_of_at=_AS_OF,
                optimizer_proposal=self._proposal("rl", {"AAA": 0.1, "CASH": 0.9}),
                rl_proposal=self._proposal("rl", {"BBB": 0.1, "CASH": 0.9}),
            )

    def test_no_proposal_at_all_fails_loudly(self):
        with self.assertRaises(ContractError):
            collect_candidates(as_of_at=_AS_OF)


class FusionIntegrationTest(unittest.TestCase):
    """ML 예측이 실제로 fusion을 통과해 optimizer 입력이 되는지 확인한다."""

    def test_ml_prediction_reaches_the_optimizer_contract(self):
        model = load_model(_artifact("ridge"))
        predictions = predict_numeric(
            model, as_of_at=_AS_OF, tickers=["AAA"],
            feature_rows=_rows(1), feature_version="v3",
        )
        fused = fuse_signals(
            ticker="AAA", as_of_at=_AS_OF, numeric_predictions=predictions,
        )
        signal = to_optimizer_signal(fused.signal)
        self.assertEqual(signal.symbol, "AAA")
        self.assertEqual(signal.horizon_days, 5)
        self.assertGreaterEqual(signal.risk_score, 0.0)
        self.assertLessEqual(signal.risk_score, 1.0)

    def test_a_worthless_model_barely_moves_the_fused_signal(self):
        """OOS 상관이 0이면 confidence가 0이라 기여가 최소로 눌린다."""
        useless = load_model(_artifact("ridge", rank_correlation=0.0))
        self.assertEqual(useless.confidence, 0.0)
        predictions = predict_numeric(
            useless, as_of_at=_AS_OF, tickers=["AAA"],
            feature_rows=_rows(1), feature_version="v3",
        )
        fused = fuse_signals(ticker="AAA", as_of_at=_AS_OF, numeric_predictions=predictions)
        self.assertGreater(fused.signal.uncertainty, 0.5)


if __name__ == "__main__":
    unittest.main()
