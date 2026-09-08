"""RL 재학습이 원장 실데이터를 쓰고 held-out 구간에서 채점하는지 검증한다."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from investment_agent.research.commands.continuous_retrain import run_continuous_retrain
from investment_agent.research.rl.contracts import RLSafetyError
from investment_agent.research.rl.features import FeatureSpec

SPEC = FeatureSpec(version="rl-test-v1", names=("momentum", "quality"))
PERIODS = tuple(f"2026-06-{day:02d}T21:00:00+00:00" for day in range(1, 13))
SYMBOLS = ("AAPL", "MSFT")


class _Repository:
    """원장 세 갈래를 그대로 흉내내는 fake. 네트워크를 쓰지 않는다."""

    def __init__(self, *, features=None, labels=None):
        self._features = features
        self._labels = labels
        self.seen_windows: list[tuple[str, str]] = []

    def current_tracked_tickers(self):
        return list(SYMBOLS)

    def rl_feature_snapshot_rows(self, symbols, *, start_as_of, end_as_of, feature_version):
        self.seen_windows.append((start_as_of, end_as_of))
        if self._features is not None:
            return list(self._features)
        return [
            {
                "feature_version": SPEC.version,
                "as_of_at": period,
                "ticker": ticker,
                "available_at": period,
                "is_available": True,
                "features": {"momentum": (0.5 if ticker == "AAPL" else -0.5), "quality": 0.4},
                "source_ids": [f"ev-{ticker}"],
                "provenance": {"origin": "test"},
            }
            for period in PERIODS
            for ticker in symbols
        ]

    def rl_training_label_rows(self, symbols, *, start_as_of, end_as_of, feature_version, label_cutoff_at):
        if self._labels is not None:
            return list(self._labels)
        return [
            {
                "feature_version": SPEC.version,
                "as_of_at": period,
                "ticker": ticker,
                "forward_end_at": period.replace("T21:", "T22:"),
                "label_available_at": period.replace("T21:", "T22:"),
                "forward_return": 0.01 if ticker == "AAPL" else -0.005,
                "benchmark_forward_return": 0.002,
            }
            for period in PERIODS
            for ticker in symbols
        ]

    def rl_historical_membership_rows(self, *, start_as_of, end_as_of):
        return [{
            "effective_at": "2026-01-01T00:00:00+00:00",
            "symbols": list(SYMBOLS),
            "source_id": "c" * 64,
            "source_kind": "historical_point_in_time",
        }]


class _StubModel:
    def __init__(self, n_assets: int):
        self.n_assets = n_assets
        self.saved_to: str | None = None

    def predict(self, observation, deterministic: bool = True):
        # action 축은 종목 수 + CASH 한 칸이다.
        size = self.n_assets + 1
        return np.ones(size, dtype=np.float32) / size, None

    def save(self, path: str) -> None:
        self.saved_to = path
        Path(path).write_bytes(b"stub-policy")


class ContinuousRetrainTest(unittest.TestCase):
    def _run(self, temp, repository, **kwargs):
        self.trained_on: list[int] = []

        def train_policy(dataset, *, timesteps):
            self.trained_on.append(len(dataset.as_of_values))
            return _StubModel(len(dataset.symbols))

        return run_continuous_retrain(
            as_of_at="2026-07-15T00:00:00+00:00",
            repository=repository,
            spec=SPEC,
            train_policy=train_policy,
            policy_dir=Path(temp),
            timesteps=8,
            **kwargs,
        )

    def test_trains_on_ledger_rows_and_scores_on_a_held_out_window(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _Repository()

            decision = self._run(temp, repository, holdout_fraction=0.25)

            # 12개 구간 중 3개는 평가용으로 빠져 학습에 쓰이지 않는다.
            self.assertEqual(self.trained_on, [9])
            self.assertEqual(decision.challenger_score.periods_evaluated, 3)
            self.assertEqual(len(repository.seen_windows), 1)

    def test_empty_feature_ledger_stops_instead_of_training_on_synthetic_data(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RLSafetyError):
                self._run(temp, _Repository(features=[]))
            self.assertEqual(self.trained_on, [])

    def test_empty_label_ledger_stops_instead_of_training_on_synthetic_data(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RLSafetyError):
                self._run(temp, _Repository(labels=[]))
            self.assertEqual(self.trained_on, [])

    def test_dry_run_writes_no_champion_files(self):
        with tempfile.TemporaryDirectory() as temp:
            self._run(temp, _Repository(), dry_run=True)

            self.assertEqual(list(Path(temp).glob("*")), [])

    def test_promotion_records_the_training_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            decision = self._run(temp, _Repository())
            active = Path(temp) / "active_policy.json"
            if not decision.is_promoted:
                self.assertFalse(active.exists())
                return
            payload = json.loads(active.read_text(encoding="utf-8"))
            self.assertEqual(payload["training"]["symbols"], list(SYMBOLS))
            self.assertEqual(payload["training"]["feature_version"], SPEC.version)
            self.assertIn("data_hash", payload["training"])
            self.assertEqual(payload["training"]["holdout_periods"], 4)


if __name__ == "__main__":
    unittest.main()
