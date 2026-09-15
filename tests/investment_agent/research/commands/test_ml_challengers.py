"""ML 후보가 자동으로 학습·비교되지만 판단 경로의 채택 파일은 절대 바뀌지 않는지."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from investment_agent.research.commands.ml_challengers import evaluate_candidates, run_ml_challengers
from investment_agent.research.datasets import build_research_dataset
from investment_agent.trading.contracts import ContractError

START = datetime(2025, 1, 1, 21, tzinfo=timezone.utc)
CUTOFF = START + timedelta(days=400)


def _dataset(*, days: int = 140, names: int = 10, signal: float = 0.02):
    rng = np.random.default_rng(3)
    features, labels = [], []
    for day in range(days):
        as_of = (START + timedelta(days=day)).isoformat()
        end = (START + timedelta(days=day + 3)).isoformat()
        for index in range(names):
            value = float(rng.normal())
            features.append({"ticker": f"T{index}", "as_of_at": as_of, "available_at": as_of,
                             "feature_version": "pit-test", "features": {"x": value},
                             "source_ids": [], "provenance": {}})
            labels.append({"ticker": f"T{index}", "as_of_at": as_of, "forward_end_at": end,
                           "label_available_at": end, "feature_version": "pit-test",
                           "label_definition": "excess_return_20d",
                           "label": signal * value + float(rng.normal(0, 0.01)), "benchmark_label": 0.0})
    return features, labels


def _build(features, labels):
    return build_research_dataset(features, labels, feature_version="pit-test",
                                  label_definition="excess_return_20d", label_cutoff_at=CUTOFF.isoformat(),
                                  feature_names=["x"])


class EvaluateCandidatesTest(unittest.TestCase):
    def test_predictive_model_is_adoptable_and_constant_model_is_not(self):
        _, rows = evaluate_candidates(_build(*_dataset()), kinds=("naive", "ridge"))
        by_kind = {row["model_kind"]: row for row in rows}
        self.assertTrue(by_kind["ridge"]["is_adoptable"])
        self.assertTrue(by_kind["ridge"]["beats_champion"])
        self.assertFalse(by_kind["naive"]["is_adoptable"])
        self.assertFalse(by_kind["naive"]["beats_champion"])

    def test_strong_icir_without_enough_oos_dates_is_not_recommended(self):
        """ICIR이 높아도 채택 조건(OOS 20일 이상 등)을 못 넘으면 champion 교체 후보가 아니다."""
        _, rows = evaluate_candidates(_build(*_dataset(days=40)), kinds=("ridge",))
        self.assertIsNotNone(rows[0]["icir"])
        self.assertFalse(rows[0]["is_adoptable"])
        self.assertFalse(rows[0]["beats_champion"])

    def test_candidate_must_beat_the_champion_icir(self):
        champion = {"artifact": {"artifact_id": "model_old"}, "out_of_sample_alpha": {"icir": 1e9}}
        _, rows = evaluate_candidates(_build(*_dataset()), kinds=("ridge",), champion=champion)
        self.assertTrue(rows[0]["is_adoptable"])
        self.assertFalse(rows[0]["beats_champion"])


class RunChallengersTest(unittest.TestCase):
    def test_candidates_are_written_but_the_active_model_is_never_touched(self):
        features, labels = _dataset()

        def export(*, output, **kwargs):
            output.write_text(json.dumps({
                "feature_version": "pit-test", "label_definition": "excess_return_20d",
                "label_cutoff_at": CUTOFF.isoformat(), "feature_names": ["x"],
                "feature_rows": features, "label_rows": labels,
            }), encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            active = Path(tmp) / "active_ml_model.json"
            candidates = Path(tmp) / "candidates"
            summary = run_ml_challengers(now=CUTOFF, candidate_dir=candidates, active_model_path=active,
                                         export=export)
            self.assertEqual(summary["status"], "evaluated")
            self.assertIsNotNone(summary["recommended_artifact_id"])
            self.assertTrue((candidates / f"{summary['recommended_artifact_id']}.json").exists())
            self.assertFalse(active.exists())

    def test_missing_data_is_recorded_not_raised(self):
        def export(**kwargs):
            raise ContractError("no forward label is confirmed before the cutoff")

        with tempfile.TemporaryDirectory() as tmp:
            summary = run_ml_challengers(now=START, candidate_dir=Path(tmp),
                                         active_model_path=Path(tmp) / "a.json", export=export)
            self.assertEqual(summary["status"], "insufficient_data")
            self.assertTrue((Path(tmp) / "latest_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
