"""Research가 feature/label full read의 PIT 필터와 무결성을 소유한다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.research.rl.contracts import FeatureSnapshot, ForwardReturnLabel
from investment_agent.research.storage.repository import ResearchStore


AS_OF = "2026-01-01T21:00:00+00:00"
LATER = "2026-01-02T21:00:00+00:00"


def _feature(*, ticker: str = "AAPL", as_of: str = AS_OF) -> FeatureSnapshot:
    return FeatureSnapshot(
        as_of_at=as_of, ticker=ticker,
        available_at=as_of, is_available=True, features={"momentum": 0.2},
        source_ids=(f"market:{ticker}:{as_of}",), provenance={"source": "test"},
    )


def _label(
    *, ticker: str = "AAPL", as_of: str = AS_OF,
    available: str = "2026-01-03T21:05:00+00:00",
) -> ForwardReturnLabel:
    return ForwardReturnLabel(
        as_of_at=as_of, ticker=ticker,
        forward_end_at="2026-01-03T21:00:00+00:00" if as_of == AS_OF else "2026-01-03T21:01:00+00:00",
        label_available_at=available, forward_return=0.03,
        benchmark_forward_return=0.01,
    )


class ResearchFullReadTest(unittest.TestCase):
    def test_feature_read_filters_ticker_window_and_exact_dates(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "research.duckdb"
            writer = ResearchStore(path)
            writer.save_rl_feature_snapshots([
                item.to_storage_row() for item in (
                    _feature(), _feature(ticker="MSFT"),
                    _feature(as_of=LATER),
                )
            ])
            reader = ResearchStore(path, read_only=True)
            rows = reader.rl_feature_snapshot_rows(
                ("aapl",), start_as_of=AS_OF, end_as_of=LATER,
                as_of_values=(AS_OF,),
            )
            self.assertEqual(rows, [_feature().to_storage_row()])
            self.assertNotIn("forward_return", rows[0])

    def test_label_read_filters_ticker_window_exact_dates_and_cutoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "research.duckdb"
            writer = ResearchStore(path)
            writer.save_rl_training_labels([
                item.to_storage_row() for item in (
                    _label(), _label(ticker="MSFT"),
                    _label(as_of=LATER),
                )
            ])
            reader = ResearchStore(path, read_only=True)
            rows = reader.rl_training_label_rows(
                ("aapl",), start_as_of=AS_OF, end_as_of=LATER,
                label_cutoff_at="2026-01-03T21:05:00+00:00",
                as_of_values=(AS_OF,),
            )
            self.assertEqual(rows, [_label().to_storage_row()])
            self.assertNotIn("features", rows[0])
            self.assertEqual(reader.rl_training_label_rows(
                ("AAPL",), start_as_of=AS_OF, end_as_of=LATER,
                label_cutoff_at="2026-01-03T21:04:00+00:00",
            ), [])

    def test_invalid_windows_are_rejected_before_read(self):
        reader = ResearchStore("missing-research.duckdb", read_only=True)
        with self.assertRaisesRegex(ValueError, "RL feature end_as_of"):
            reader.rl_feature_snapshot_rows(
                ("AAPL",), start_as_of=LATER, end_as_of=AS_OF,
            )
        with self.assertRaisesRegex(ValueError, "label_cutoff_at"):
            reader.rl_training_label_rows(
                ("AAPL",), start_as_of=AS_OF, end_as_of=LATER,
                label_cutoff_at=AS_OF,
            )

    def test_tampered_rows_fail_closed_on_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "research.duckdb"
            writer = ResearchStore(path)
            feature = _feature().to_storage_row()
            feature["input_hash"] = "0" * 64
            feature["record_key"] = f"rl-v1:{AS_OF}:AAPL"
            writer.upsert_records("rl_feature_snapshots", [feature], key="record_key")
            reader = ResearchStore(path, read_only=True)
            with self.assertRaisesRegex(RuntimeError, "input_hash"):
                reader.rl_feature_snapshot_rows(
                    ("AAPL",), start_as_of=AS_OF, end_as_of=LATER,
                )

            label = _label().to_storage_row()
            label["label_id"] = "tampered"
            label["record_key"] = f"rl-v1:{AS_OF}:AAPL"
            writer.upsert_records("rl_training_labels", [label], key="record_key")
            with self.assertRaisesRegex(RuntimeError, "label_id"):
                reader.rl_training_label_rows(
                    ("AAPL",), start_as_of=AS_OF, end_as_of=LATER,
                    label_cutoff_at="2026-01-04T00:00:00+00:00",
                )


if __name__ == "__main__":
    unittest.main()
