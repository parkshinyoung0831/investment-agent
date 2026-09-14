from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from investment_agent.research.ml_inference import load_model
from investment_agent.research.ml_serving import compute_ml_fusion, latest_cross_section
from investment_agent.trading.portfolio.contracts import SecurityProposal

AS_OF = datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc)
FEATURE_DAY = AS_OF - timedelta(hours=20)


def _artifact(*, mean_ic: float, t_stat: float, coefficient: float = 0.01) -> dict:
    return {
        "artifact": {
            "artifact_id": "model_test", "model_kind": "ridge", "feature_version": "pit-test",
            "horizon_days": 5, "out_of_sample": {"rank_correlation": 0.9, "direction_accuracy": 0.6},
        },
        "model_state": {"coefficients": [coefficient], "intercept": 0.0},
        "feature_names": ["evidence_domain_count"],
        "out_of_sample_alpha": {"mean_ic": mean_ic, "ic_t_stat": t_stat},
    }


def _proposal(ticker: str, signal: str, expected: float) -> SecurityProposal:
    return SecurityProposal(
        ticker=ticker, as_of_at=AS_OF.isoformat(), signal=signal, probability_up=0.55, confidence=0.6,
        expected_excess_return=expected, target_weight=0.0, reasoning=("llm",), evidence_ids=("EV-1",),
    )


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


class MlServingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "active_ml_model.json"
        self.repository = FakeRepository([_row("AAPL", 8.0), _row("MSFT", -8.0), _row("NVDA", 0.0)])

    def write(self, payload):
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def test_without_an_adopted_model_the_proposals_are_unchanged(self):
        proposals = [_proposal("AAPL", "open", 0.01)]
        fused, outcome = compute_ml_fusion(self.repository, proposals, as_of_at=AS_OF, model_path=self.path)
        self.assertEqual(fused, proposals)
        self.assertFalse(outcome.applied)
        self.assertIn("no adopted", outcome.reason)

    def test_insignificant_ic_is_never_fused(self):
        self.write(_artifact(mean_ic=0.04, t_stat=1.2))
        proposals = [_proposal("AAPL", "open", 0.01)]
        fused, outcome = compute_ml_fusion(self.repository, proposals, as_of_at=AS_OF, model_path=self.path)
        self.assertEqual(fused, proposals)
        self.assertIn("significant", outcome.reason)

    def test_significant_model_moves_expected_return_but_keeps_the_action(self):
        self.write(_artifact(mean_ic=0.05, t_stat=3.0))
        proposals = [_proposal("AAPL", "open", 0.0), _proposal("MSFT", "exit", 0.0)]
        fused, outcome = compute_ml_fusion(
            self.repository, proposals, as_of_at=AS_OF, model_path=self.path, enabled=True,
        )
        self.assertTrue(outcome.applied)
        by_ticker = {item.ticker: item for item in fused}
        # ML은 AAPL +8% (0.01×8), MSFT -8%를 예측한다.
        self.assertGreater(by_ticker["AAPL"].expected_excess_return, 0.0)
        self.assertLess(by_ticker["MSFT"].expected_excess_return, 0.0)
        self.assertEqual(by_ticker["MSFT"].signal, "exit")
        self.assertEqual(set(outcome.contributions["AAPL"]), {"numeric", "tradingagents"})

    def test_ml_cannot_lift_a_negative_opinion_above_zero(self):
        self.write(_artifact(mean_ic=0.08, t_stat=4.0))
        fused, _ = compute_ml_fusion(
            self.repository, [_proposal("AAPL", "exit", -0.01)], as_of_at=AS_OF, model_path=self.path, enabled=True,
        )
        self.assertLessEqual(fused[0].expected_excess_return, 0.0)

    def test_disabled_flag_records_the_comparison_without_applying(self):
        self.write(_artifact(mean_ic=0.05, t_stat=3.0))
        proposals = [_proposal("AAPL", "open", 0.0)]
        fused, outcome = compute_ml_fusion(
            self.repository, proposals, as_of_at=AS_OF, model_path=self.path, enabled=False,
        )
        self.assertEqual(fused, proposals)
        self.assertTrue(outcome.available)
        self.assertFalse(outcome.applied)
        self.assertNotEqual(outcome.fused_expected_returns["AAPL"], 0.0)

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
                    "feature_version": "pit-test", "label_definition": "forward_return_5d",
                    "label": 0.02 * signal + float(rng.normal(0, 0.01)), "benchmark_label": 0.0,
                })
        dataset = build_research_dataset(
            features, labels, feature_version="pit-test", label_definition="forward_return_5d",
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


if __name__ == "__main__":
    unittest.main()
