"""ML 후보가 자동으로 학습·비교되고, 기준을 넘으면 채택되고 순위 능력을 잃으면 해제되는지."""
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
                             "features": {"x": value},
                             "source_ids": [], "provenance": {}})
            labels.append({"ticker": f"T{index}", "as_of_at": as_of, "forward_end_at": end,
                           "label_available_at": end,
                           "label_definition": "excess_return_20d",
                           "label": signal * value + float(rng.normal(0, 0.01)), "benchmark_label": 0.0})
    return features, labels


def _build(features, labels):
    return build_research_dataset(features, labels,
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


def _export(features, labels):
    def export(*, output, **kwargs):
        output.write_text(json.dumps({
            "label_definition": "excess_return_20d",
            "label_cutoff_at": CUTOFF.isoformat(), "feature_names": ["x"],
            "feature_rows": features, "label_rows": labels,
        }), encoding="utf-8")
    return export


class RunChallengersTest(unittest.TestCase):
    def test_a_candidate_that_passes_the_bar_is_adopted_and_a_repeat_run_keeps_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            active = Path(tmp) / "active_ml_model.json"
            candidates = Path(tmp) / "candidates"
            summary = run_ml_challengers(now=CUTOFF, candidate_dir=candidates, active_model_path=active,
                                         export=_export(*_dataset()))
            self.assertEqual(summary["status"], "evaluated")
            self.assertEqual("adopted", summary["adoption"]["action"])
            self.assertTrue((candidates / f"{summary['recommended_artifact_id']}.json").exists())
            adopted = json.loads(active.read_text(encoding="utf-8"))["artifact"]["artifact_id"]
            self.assertEqual(summary["recommended_artifact_id"], adopted)
            # 같은 데이터로 다시 돌면 더 나은 후보가 없고 champion은 순위 능력을 유지한다.
            again = run_ml_challengers(now=CUTOFF, candidate_dir=candidates, active_model_path=active,
                                       export=_export(*_dataset()))
            self.assertEqual("kept", again["adoption"]["action"])
            self.assertEqual("holds", again["champion_recheck"]["status"])

    def test_a_champion_that_lost_its_edge_is_retired(self):
        with tempfile.TemporaryDirectory() as tmp:
            active = Path(tmp) / "active_ml_model.json"
            candidates = Path(tmp) / "candidates"
            run_ml_challengers(now=CUTOFF, candidate_dir=candidates, active_model_path=active,
                               export=_export(*_dataset()))
            self.assertTrue(active.exists())
            # 신호가 사라진 데이터: 새 후보도 기준을 못 넘고 champion은 더 이상 맞히지 못한다.
            summary = run_ml_challengers(now=CUTOFF, candidate_dir=candidates, active_model_path=active,
                                         export=_export(*_dataset(signal=0.0)))
            self.assertEqual("retired", summary["adoption"]["action"])
            self.assertEqual("lost_edge", summary["champion_recheck"]["status"])
            self.assertFalse(active.exists())
            self.assertTrue(any((candidates / "retired").glob("*.json")))

    def test_a_stale_champion_is_replaced_by_any_candidate_that_passes_the_bar(self):
        """옛 champion의 ICIR은 지난 데이터의 숫자다. 순위 능력을 잃었으면 그것을 넘을 필요가 없다."""
        with tempfile.TemporaryDirectory() as tmp:
            active = Path(tmp) / "active_ml_model.json"
            candidates = Path(tmp) / "candidates"
            first = run_ml_challengers(now=CUTOFF, candidate_dir=candidates, active_model_path=active,
                                       export=_export(*_dataset()))
            reversed_market = run_ml_challengers(now=CUTOFF, candidate_dir=candidates, active_model_path=active,
                                                 export=_export(*_dataset(signal=-0.02)))
            self.assertEqual("lost_edge", reversed_market["champion_recheck"]["status"])
            self.assertEqual("adopted", reversed_market["adoption"]["action"])
            self.assertEqual(first["recommended_artifact_id"], reversed_market["adoption"]["replaced"])

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
