from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from investment_agent.research.ml_inference import load_model
from investment_agent.research.ml_serving import champion_forecast, latest_cross_section

AS_OF = datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc)
FEATURE_DAY = AS_OF - timedelta(hours=20)


def _artifact(*, mean_ic: float, t_stat: float, coefficient: float = 0.01, horizon: int = 20,
              label: str = "excess_return_20d") -> dict:
    return {
        "artifact": {
            "artifact_id": "model_test", "model_kind": "ridge", "feature_version": "pit-test",
            "horizon_days": horizon, "out_of_sample": {"rank_correlation": 0.9, "direction_accuracy": 0.6},
        },
        "model_state": {"coefficients": [coefficient], "intercept": 0.0},
        "feature_names": ["evidence_domain_count"],
        "out_of_sample_alpha": {"mean_ic": mean_ic, "ic_t_stat": t_stat},
        "dataset_manifest": {"label_definition": label},
    }


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows

    def current_tracked_tickers(self):
        return {row["ticker"] for row in self.rows}

    def rl_feature_snapshot_rows(self, symbols, *, start_as_of, end_as_of, feature_version):
        return [row for row in self.rows if row["feature_version"] == feature_version]


def _row(ticker: str, value: float, *, as_of: datetime = FEATURE_DAY, available: datetime | None = None):
    return {
        "ticker": ticker, "feature_version": "pit-test", "as_of_at": as_of.isoformat(),
        "available_at": (available or as_of).isoformat(), "is_available": True,
        "features": {"evidence_domain_count": value, "missing_domain_count": 0.0},
        "source_ids": [f"market:{ticker}"], "provenance": {"market": "test"},
    }


class ChampionForecastTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "active_ml_model.json"
        self.repository = FakeRepository([_row("AAPL", 8.0), _row("MSFT", -8.0), _row("NVDA", 0.0)])

    def write(self, payload):
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def forecast(self, tickers=("AAPL", "MSFT")):
        return champion_forecast(self.repository, tickers, as_of_at=AS_OF, model_path=self.path)

    def test_without_an_adopted_model_there_is_no_forecast(self):
        outcome = self.forecast()
        self.assertFalse(outcome.is_available)
        self.assertIn("no adopted", outcome.reason)

    def test_insignificant_ic_is_never_used(self):
        self.write(_artifact(mean_ic=0.04, t_stat=1.2))
        outcome = self.forecast()
        self.assertFalse(outcome.is_available)
        self.assertIn("significant", outcome.reason)

    def test_significant_model_predicts_excess_returns_with_its_oos_confidence(self):
        self.write(_artifact(mean_ic=0.03, t_stat=3.0))
        outcome = self.forecast()
        self.assertTrue(outcome.is_available)
        self.assertAlmostEqual(outcome.confidence, 0.3)
        # 계수 0.01 × feature 8 = +8%, -8%
        self.assertAlmostEqual(outcome.expected_excess_returns["AAPL"], 0.08)
        self.assertAlmostEqual(outcome.expected_excess_returns["MSFT"], -0.08)
        self.assertEqual(outcome.model_artifact_id, "model_test")

    def test_model_trained_on_raw_returns_is_refused(self):
        self.write(_artifact(mean_ic=0.05, t_stat=3.0, label="forward_return_20d"))
        outcome = self.forecast()
        self.assertFalse(outcome.is_available)
        self.assertIn("excess return", outcome.reason)

    def test_model_trained_on_another_horizon_is_not_scaled_into_the_signal(self):
        self.write(_artifact(mean_ic=0.05, t_stat=3.0, horizon=5, label="excess_return_5d"))
        outcome = self.forecast()
        self.assertFalse(outcome.is_available)
        self.assertIn("horizon", outcome.reason)

    def test_cross_section_uses_one_date_and_ignores_unpublished_rows(self):
        rows = [
            _row("AAPL", 1.0, as_of=FEATURE_DAY - timedelta(days=1)),
            _row("AAPL", 2.0),
            _row("MSFT", 3.0),
            _row("NVDA", 9.0, available=AS_OF + timedelta(minutes=5)),
        ]
        as_of, snapshots = latest_cross_section(rows, as_of_at=AS_OF, lookback_days=3)
        self.assertEqual(as_of, FEATURE_DAY.isoformat())
        self.assertEqual([item.ticker for item in snapshots], ["AAPL", "MSFT"])

    def test_ic_based_confidence_replaces_pooled_rank_correlation(self):
        self.assertAlmostEqual(load_model(_artifact(mean_ic=0.03, t_stat=2.5)).confidence, 0.3)
        self.assertEqual(load_model(_artifact(mean_ic=0.03, t_stat=1.5)).confidence, 0.0)
        legacy = _artifact(mean_ic=0.0, t_stat=0.0)
        legacy.pop("out_of_sample_alpha")
        self.assertAlmostEqual(load_model(legacy).confidence, 0.8)


class SignalHorizonContractTest(unittest.TestCase):
    def test_llm_schema_states_the_signal_horizon(self):
        from investment_agent.trading.decision.constants import SIGNAL_HORIZON_DAYS
        from investment_agent.trading.decision.llm.agents.tradingagents_adapter import SECURITY_PROPOSAL_SCHEMA

        for field in ("expected_excess_return", "probability_up"):
            self.assertIn(f"{SIGNAL_HORIZON_DAYS} trading days", SECURITY_PROPOSAL_SCHEMA[field])

    def test_llm_schema_asks_for_a_thesis_not_a_trade(self):
        from investment_agent.trading.decision.llm.agents.tradingagents_adapter import SECURITY_PROPOSAL_SCHEMA

        self.assertNotIn("signal", SECURITY_PROPOSAL_SCHEMA)
        self.assertNotIn("target_weight", SECURITY_PROPOSAL_SCHEMA)
        for field in ("thesis", "hard_constraint", "key_risks"):
            self.assertIn(field, SECURITY_PROPOSAL_SCHEMA)

    def test_training_refuses_labels_that_are_not_excess_returns(self):
        from investment_agent.research.training.baseline import label_horizon_days

        self.assertEqual(label_horizon_days("excess_return_20d"), 20)
        for invalid in ("excess_return", "forward_return_20d"):
            with self.assertRaises(ValueError):
                label_horizon_days(invalid)


class TrainingRecordsAlphaTest(unittest.TestCase):
    def test_training_result_carries_oos_cross_sectional_alpha(self):
        from investment_agent.research.datasets import build_research_dataset
        from investment_agent.research.training.baseline import train_baseline_dataset

        rng = np.random.default_rng(0)
        features, labels = [], []
        start = datetime(2025, 1, 1, 21, tzinfo=timezone.utc)
        for day in range(40):
            as_of = (start + timedelta(days=day)).isoformat()
            for name in range(8):
                signal = float(rng.normal())
                ticker = f"T{name}"
                features.append({
                    "ticker": ticker, "as_of_at": as_of, "available_at": as_of, "feature_version": "pit-test",
                    "features": {"x": signal}, "source_ids": [], "provenance": {},
                })
                labels.append({
                    "ticker": ticker, "as_of_at": as_of,
                    "forward_end_at": (start + timedelta(days=day + 7)).isoformat(),
                    "label_available_at": (start + timedelta(days=day + 7)).isoformat(),
                    "feature_version": "pit-test", "label_definition": "excess_return_20d",
                    "label": 0.02 * signal + float(rng.normal(0, 0.01)), "benchmark_label": 0.0,
                })
        dataset = build_research_dataset(
            features, labels, feature_version="pit-test", label_definition="excess_return_20d",
            label_cutoff_at=(start + timedelta(days=60)).isoformat(), feature_names=["x"],
        )
        rows = len(dataset.rows)
        result = train_baseline_dataset(
            dataset, model_kind="ridge",
            train_split=(0, rows // 2), validation_split=(rows // 2, rows * 3 // 4),
            test_split=(rows * 3 // 4, rows),
        )
        self.assertIsNotNone(result.oos_alpha)
        self.assertGreater(result.oos_alpha.mean_ic, 0.3)
        # 모델에 적힌 기간은 label 정의가 정한다 — 다른 기간과 섞이지 않게.
        self.assertEqual(result.artifact.horizon_days, 20)


if __name__ == "__main__":
    unittest.main()
