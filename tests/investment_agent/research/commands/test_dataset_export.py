"""dataset export와 purge된 split이 미래 label 누수를 막는지 고정한다."""
from __future__ import annotations

import json
import statistics
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.research.commands.export_dataset import export_dataset
from investment_agent.research.features.layer import (
    ALWAYS_KNOWN_FEATURES,
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    MISSING_SUFFIX,
    OPTIONAL_FEATURES,
)
from investment_agent.research.datasets import build_research_dataset, load_dataset_json
from investment_agent.research.training.walk_forward import dataset_periods, purged_row_splits

_START = datetime(2026, 3, 3, 22, tzinfo=timezone.utc)
_TICKERS = ("AAA", "BBB", "CCC")
_HORIZON_DAYS = 7


def _features(seed: float, *, drop_technical: bool = False) -> dict:
    values = {}
    for name in ALWAYS_KNOWN_FEATURES:
        values[name] = 1.0
    for name in OPTIONAL_FEATURES:
        missing = drop_technical and name.startswith("technical_")
        values[name] = None if missing else seed
        values[f"{name}{MISSING_SUFFIX}"] = 1.0 if missing else 0.0
    return values


class _Repository:
    """원장 두 표만 흉내낸다."""

    def __init__(self, periods: int = 12):
        self.periods = periods

    def current_tracked_tickers(self):
        return list(_TICKERS)

    def _as_of(self, index: int) -> datetime:
        return _START + timedelta(days=7 * index)

    def rl_feature_snapshot_rows(self, symbols, *, start_as_of, end_as_of, feature_version):
        rows = []
        for index in range(self.periods):
            as_of = self._as_of(index)
            for position, ticker in enumerate(_TICKERS):
                rows.append({
                    "feature_version": feature_version,
                    "as_of_at": as_of.isoformat(),
                    "ticker": ticker,
                    "available_at": (as_of - timedelta(hours=1)).isoformat(),
                    "is_available": True,
                    "features": _features(
                        0.01 * (index + position),
                        drop_technical=(ticker == "CCC"),
                    ),
                    "source_ids": [f"EV-{ticker}-{index}"],
                    "provenance": {"definition_hash": "x", "source_kind": "live_shadow"},
                })
        return rows

    def rl_training_label_rows(self, symbols, *, start_as_of, end_as_of, feature_version, label_cutoff_at):
        cutoff = parse_datetime(label_cutoff_at)
        rows = []
        for index in range(self.periods):
            as_of = self._as_of(index)
            end = as_of + timedelta(days=_HORIZON_DAYS)
            if end > cutoff:
                continue
            for position, ticker in enumerate(_TICKERS):
                rows.append({
                    "feature_version": feature_version,
                    "as_of_at": as_of.isoformat(),
                    "ticker": ticker,
                    "forward_end_at": end.isoformat(),
                    "label_available_at": end.isoformat(),
                    "forward_return": 0.001 * (index - position),
                    "benchmark_forward_return": 0.0005,
                })
        return rows


class ExportDatasetTest(unittest.TestCase):
    def _export(self, repository, output=None, cutoff=None):
        end = _START + timedelta(days=7 * repository.periods + 30)
        return export_dataset(
            start_as_of=(_START - timedelta(days=1)).isoformat(),
            end_as_of=end.isoformat(),
            label_cutoff_at=(cutoff or end).isoformat(),
            horizon_days=5,
            output=output,
            repository=repository,
        )

    def test_export_writes_a_dataset_that_reloads_into_a_matrix(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "dataset.json"
            payload = self._export(_Repository(), output=path)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["detail"]["periods"], 12)
            self.assertEqual(payload["detail"]["features"], len(FEATURE_COLUMNS))
            dataset = load_dataset_json(path)
            self.assertEqual(dataset.features.shape, (36, len(FEATURE_COLUMNS)))
            self.assertEqual(dataset.manifest.feature_version, FEATURE_VERSION)

    def test_missing_values_are_imputed_within_the_same_period_only(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "dataset.json"
            self._export(_Repository(), output=path)
            document = json.loads(path.read_text(encoding="utf-8"))
            rows = {(row["as_of_at"], row["ticker"]): row for row in document["feature_rows"]}
            first = _START.isoformat()
            filled = rows[(first, "CCC")]["features"]
            peers = [rows[(first, name)]["features"]["technical_rsi14"] for name in ("AAA", "BBB")]
            self.assertEqual(filled["technical_rsi14"], statistics.median(peers))
            # 대체됐어도 결측이었다는 사실은 남는다.
            self.assertEqual(filled[f"technical_rsi14{MISSING_SUFFIX}"], 1.0)

    def test_snapshot_without_a_confirmed_label_is_excluded(self):
        repository = _Repository()
        # 마지막 두 시점의 label 구간이 아직 안 끝난 cutoff를 쓴다.
        cutoff = _START + timedelta(days=7 * 9 + _HORIZON_DAYS)
        payload = self._export(repository, cutoff=cutoff)
        self.assertEqual(payload["detail"]["periods"], 10)
        self.assertEqual(payload["detail"]["rows"], 30)

    def test_export_fails_loudly_when_no_label_is_confirmed(self):
        repository = _Repository()
        with self.assertRaises(ContractError):
            self._export(repository, cutoff=_START - timedelta(days=1))


class PurgedSplitTest(unittest.TestCase):
    def _dataset(self, periods: int = 12):
        repository = _Repository(periods=periods)
        end = _START + timedelta(days=7 * periods + 30)
        features = repository.rl_feature_snapshot_rows(
            _TICKERS, start_as_of=_START.isoformat(), end_as_of=end.isoformat(),
            feature_version=FEATURE_VERSION,
        )
        labels = repository.rl_training_label_rows(
            _TICKERS, start_as_of=_START.isoformat(), end_as_of=end.isoformat(),
            feature_version=FEATURE_VERSION, label_cutoff_at=end.isoformat(),
        )
        feature_rows = [{
            "ticker": row["ticker"], "as_of_at": row["as_of_at"],
            "available_at": row["available_at"], "feature_version": row["feature_version"],
            "features": {name: (0.0 if value is None else value)
                         for name, value in row["features"].items()},
            "source_ids": row["source_ids"], "provenance": row["provenance"],
        } for row in features]
        label_rows = [{
            "ticker": row["ticker"], "as_of_at": row["as_of_at"],
            "forward_end_at": row["forward_end_at"],
            "label_available_at": row["label_available_at"],
            "feature_version": row["feature_version"],
            "label_definition": "forward_return_5d",
            "label": row["forward_return"], "benchmark_label": row["benchmark_forward_return"],
        } for row in labels]
        return build_research_dataset(
            feature_rows, label_rows, feature_version=FEATURE_VERSION,
            label_definition="forward_return_5d", label_cutoff_at=end.isoformat(),
            feature_names=list(FEATURE_COLUMNS),
        )

    def test_periods_group_every_ticker_of_the_same_as_of(self):
        periods = dataset_periods(self._dataset())
        self.assertEqual(len(periods), 12)
        for _, _, start, end in periods:
            self.assertEqual(end - start, len(_TICKERS))

    def test_a_single_as_of_is_never_split_across_two_sets(self):
        dataset = self._dataset()
        train, validation, test = purged_row_splits(dataset)
        for bounds in (train, validation, test):
            start, end = bounds
            self.assertEqual((end - start) % len(_TICKERS), 0, "시점이 쪼개졌다")

    def test_train_labels_close_before_validation_begins(self):
        dataset = self._dataset()
        train, validation, _ = purged_row_splits(dataset)
        latest_train_label = max(
            parse_datetime(dataset.labels[index].forward_end_at)
            for index in range(*train)
        )
        first_validation_as_of = parse_datetime(dataset.rows[validation[0]].as_of_at)
        self.assertLess(latest_train_label, first_validation_as_of)

    def test_validation_labels_close_before_the_test_set_begins(self):
        dataset = self._dataset()
        _, validation, test = purged_row_splits(dataset)
        latest_validation_label = max(
            parse_datetime(dataset.labels[index].forward_end_at)
            for index in range(*validation)
        )
        first_test_as_of = parse_datetime(dataset.rows[test[0]].as_of_at)
        self.assertLess(latest_validation_label, first_test_as_of)

    def test_splits_never_overlap(self):
        dataset = self._dataset()
        train, validation, test = purged_row_splits(dataset)
        self.assertLessEqual(train[1], validation[0])
        self.assertLessEqual(validation[1], test[0])

    def test_too_few_periods_fails_loudly_instead_of_leaking(self):
        with self.assertRaises(ContractError):
            purged_row_splits(self._dataset(periods=4))


if __name__ == "__main__":
    unittest.main()
