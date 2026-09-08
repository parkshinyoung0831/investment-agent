from __future__ import annotations

import unittest

import pandas as pd

from investment_agent.research.qlib_adapter import QlibPITAdapter, QlibSegments
from investment_agent.research.rl.contracts import FeatureSnapshot


def _snapshot(ticker: str, as_of_at: str, value: float) -> FeatureSnapshot:
    return FeatureSnapshot(
        feature_version="v1",
        as_of_at=as_of_at,
        ticker=ticker,
        available_at=as_of_at,
        is_available=True,
        features={"momentum_5d": value, "volatility_20d": value / 2},
        source_ids=(f"source:{ticker}:{as_of_at}",),
        provenance={"definition_hash": "a" * 64},
    )


class QlibAdapterTest(unittest.TestCase):
    def test_feature_snapshots_export_to_qlib_multiindex_without_vendor_data(self):
        snapshots = (
            _snapshot("AAPL", "2026-01-02T21:00:00+00:00", 0.1),
            _snapshot("MSFT", "2026-01-02T21:00:00+00:00", 0.2),
        )
        labels = {snapshot.snapshot_id: index * 0.01 for index, snapshot in enumerate(snapshots)}
        frame = QlibPITAdapter.to_frame(snapshots, labels=labels)
        self.assertEqual(frame.index.names, ["datetime", "instrument"])
        self.assertIsInstance(frame.columns, pd.MultiIndex)
        self.assertIn(("feature", "momentum_5d"), frame.columns)
        self.assertIn(("label", "LABEL0"), frame.columns)

    def test_segments_keep_train_validation_oos_separate(self):
        segments = QlibSegments(
            train=("2020-01-01", "2023-12-31"),
            valid=("2024-01-01", "2024-12-31"),
            test=("2025-01-01", "2025-12-31"),
        )
        self.assertEqual(set(segments.to_dict()), {"train", "valid", "test"})


if __name__ == "__main__":
    unittest.main()
