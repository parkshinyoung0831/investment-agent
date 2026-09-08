"""원장 행에서 RL 학습용 FeatureDataset을 조립하는 경로를 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.research.rl.contracts import RLSafetyError
from investment_agent.research.rl.features import FeatureSpec, load_training_set

SPEC = FeatureSpec(version="v3", names=("momentum_20d", "volatility_20d"))
PERIODS = ("2026-08-03T00:00:00+00:00", "2026-08-10T00:00:00+00:00")
CUTOFF = "2026-09-01T00:00:00+00:00"


def _feature_row(as_of_at: str, ticker: str, values: tuple[float, float]):
    return {
        "feature_version": "v3",
        "as_of_at": as_of_at,
        "ticker": ticker,
        "available_at": as_of_at,
        "is_available": True,
        "features": dict(zip(SPEC.names, values, strict=True)),
        "source_ids": [f"ev-{ticker}"],
        "provenance": {"origin": "test"},
    }


def _label_row(as_of_at: str, ticker: str, forward: float, benchmark: float):
    end = as_of_at.replace("-03T", "-08T").replace("-10T", "-15T")
    return {
        "feature_version": "v3",
        "as_of_at": as_of_at,
        "ticker": ticker,
        "forward_end_at": end,
        "label_available_at": end,
        "forward_return": forward,
        "benchmark_forward_return": benchmark,
    }


class _Repository:
    def __init__(self, *, features=None, labels=None, membership=None):
        self._features = features
        self._labels = labels
        self._membership = membership

    def rl_feature_snapshot_rows(self, symbols, *, start_as_of, end_as_of, feature_version):
        if self._features is not None:
            return list(self._features)
        return [
            _feature_row(period, ticker, (0.1 * index, 0.2))
            for period in PERIODS
            for index, ticker in enumerate(symbols)
        ]

    def rl_training_label_rows(self, symbols, *, start_as_of, end_as_of, feature_version, label_cutoff_at):
        if self._labels is not None:
            return list(self._labels)
        return [
            _label_row(period, ticker, 0.01 * (index + 1), 0.004)
            for period in PERIODS
            for index, ticker in enumerate(symbols)
        ]

    def rl_historical_membership_rows(self, *, start_as_of, end_as_of):
        if self._membership is not None:
            return list(self._membership)
        return [{
            "effective_at": "2026-01-01T00:00:00+00:00",
            "symbols": ["AAPL", "MSFT"],
            "source_id": "a" * 64,
            "source_kind": "historical_point_in_time",
        }]


class LoadTrainingSetTest(unittest.TestCase):
    def _load(self, repository, symbols=("AAPL", "MSFT")):
        return load_training_set(
            repository,
            symbols=symbols,
            start_as_of=PERIODS[0],
            end_as_of=PERIODS[-1],
            label_cutoff_at=CUTOFF,
            spec=SPEC,
        )

    def test_builds_a_dataset_from_ledger_rows(self):
        result = self._load(_Repository())

        dataset = result.dataset
        self.assertEqual(dataset.symbols, ("AAPL", "MSFT"))
        self.assertEqual(dataset.feature_names, SPEC.names)
        self.assertEqual(dataset.as_of_values, PERIODS)
        self.assertEqual(dataset.features.shape, (2, 2, 2))
        self.assertTrue(dataset.availability.all())
        self.assertEqual(result.membership_hash, result.membership_hash)
        self.assertTrue(result.data_hash)

    def test_empty_feature_ledger_fails_instead_of_returning_a_dataset(self):
        with self.assertRaises(RLSafetyError):
            self._load(_Repository(features=[]))

    def test_empty_label_ledger_fails_instead_of_returning_a_dataset(self):
        with self.assertRaises(RLSafetyError):
            self._load(_Repository(labels=[]))

    def test_symbol_outside_historical_membership_is_not_trainable(self):
        membership = [{
            "effective_at": "2026-01-01T00:00:00+00:00",
            "symbols": ["AAPL"],
            "source_id": "b" * 64,
            "source_kind": "historical_point_in_time",
        }]

        dataset = self._load(_Repository(membership=membership)).dataset

        self.assertTrue(dataset.availability[:, 0].all())
        self.assertFalse(dataset.availability[:, 1].any())

    def test_missing_membership_ledger_fails_closed(self):
        with self.assertRaises(RLSafetyError):
            self._load(_Repository(membership=[]))


if __name__ == "__main__":
    unittest.main()
