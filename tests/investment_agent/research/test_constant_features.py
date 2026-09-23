"""학습 구간에서 값이 변하지 않는 열은 학습이 성공해도 드러난다(RS-2)."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import numpy as np

from investment_agent.research.datasets import build_research_dataset
from investment_agent.research.training import baseline
from investment_agent.research.training.baseline import constant_feature_names, train_baseline_dataset


def _dataset(*, dead_column: bool):
    rng = np.random.default_rng(1)
    start = datetime(2025, 1, 1, 21, tzinfo=timezone.utc)
    features, labels = [], []
    for day in range(40):
        as_of = (start + timedelta(days=day)).isoformat()
        for name in range(8):
            signal = float(rng.normal())
            ticker = f"T{name}"
            values = {"x": signal, "technical_rsi14": 50.0 if dead_column else float(rng.normal())}
            features.append({"ticker": ticker, "as_of_at": as_of, "available_at": as_of,
                             "features": values, "source_ids": [], "provenance": {}})
            labels.append({
                "ticker": ticker, "as_of_at": as_of,
                "forward_end_at": (start + timedelta(days=day + 7)).isoformat(),
                "label_available_at": (start + timedelta(days=day + 7)).isoformat(),
                "label_definition": "excess_return_20d",
                "label": 0.02 * signal + float(rng.normal(0, 0.01)), "benchmark_label": 0.0,
            })
    return build_research_dataset(
        features, labels, label_definition="excess_return_20d",
        label_cutoff_at=(start + timedelta(days=60)).isoformat(), feature_names=["x", "technical_rsi14"],
    )


def _train(dataset):
    rows = len(dataset.rows)
    return train_baseline_dataset(
        dataset, model_kind="ridge",
        train_split=(0, rows // 2), validation_split=(rows // 2, rows * 3 // 4), test_split=(rows * 3 // 4, rows),
    )


class ConstantFeatureTest(unittest.TestCase):
    def test_detects_only_the_column_that_never_moves(self) -> None:
        dataset = _dataset(dead_column=True)
        self.assertEqual(constant_feature_names(dataset, tuple(range(len(dataset.rows)))), ("technical_rsi14",))

    def test_a_varying_column_is_not_reported(self) -> None:
        dataset = _dataset(dead_column=False)
        self.assertEqual(constant_feature_names(dataset, tuple(range(len(dataset.rows)))), ())

    def test_training_result_names_the_dead_columns_and_logs_a_warning(self) -> None:
        with mock.patch.object(baseline.log, "warning") as warning:
            result = _train(_dataset(dead_column=True))
        self.assertEqual(result.constant_features, ("technical_rsi14",))
        # 모델 입력과 artifact의 열 목록에서 빠진다 — 쓰지 않는 열을 쓴다고 적지 않는다.
        self.assertEqual(("x",), result.feature_names)
        from investment_agent.research.commands.train_baseline import artifact_document
        document = artifact_document(result, _dataset(dead_column=True))
        self.assertEqual(["x"], document["feature_names"])
        self.assertEqual(["technical_rsi14"], document["excluded_constant_features"])
        self.assertEqual(1, len(document["model_state"]["coefficients"]))
        warning.assert_called_once()
        self.assertIn("technical_rsi14", warning.call_args.args[-1])

    def test_no_warning_when_every_column_varies(self) -> None:
        with mock.patch.object(baseline.log, "warning") as warning:
            result = _train(_dataset(dead_column=False))
        self.assertEqual(result.constant_features, ())
        warning.assert_not_called()

    def test_challenger_summary_row_carries_the_names(self) -> None:
        from investment_agent.research.commands.ml_challengers import evaluate_candidates

        _documents, rows = evaluate_candidates(_dataset(dead_column=True), kinds=("ridge",))
        trained = [row for row in rows if row.get("status") == "trained"]
        self.assertEqual(trained[0]["constant_features"], ["technical_rsi14"])


class ChallengerComparisonCountTest(unittest.TestCase):
    def test_candidates_are_judged_against_the_number_of_kinds_compared(self) -> None:
        """네 후보를 견줘 최고를 고르면 t 문턱도 네 후보 몫으로 올라야 한다(RS-17)."""
        from investment_agent.research.commands import ml_challengers

        seen: list[int] = []
        original = ml_challengers.check_adoptable

        def spy(document, *, comparisons=1):
            seen.append(comparisons)
            return original(document, comparisons=comparisons)

        with mock.patch.object(ml_challengers, "check_adoptable", side_effect=spy):
            ml_challengers.evaluate_candidates(_dataset(dead_column=False), kinds=("naive", "ridge"))
        self.assertEqual(seen, [2, 2])


if __name__ == "__main__":
    unittest.main()
