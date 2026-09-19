"""학습 표본 매니페스트용 scalar 조회가 PIT·payload 경계를 지키는지 검증한다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_agent.research.storage.repository import ResearchStore


class TrainingSampleMetadataTest(unittest.TestCase):
    def test_scalar_projection_filters_version_ticker_window_and_label_cutoff(self):
        point = "2026-01-03T00:00:00+00:00"
        later_point = "2026-01-04T00:00:00+00:00"
        with tempfile.TemporaryDirectory() as temporary:
            store = ResearchStore(Path(temporary) / "research.duckdb")
            store.upsert_records("rl_feature_snapshots", [
                {
                    "record_key": f"v5:{point}:AAA", "ticker": "AAA", "as_of_at": point,
                    "feature_version": "v5", "input_hash": "aaa-hash",
                    "features": {"large_payload": [1, 2, 3]},
                },
                {
                    "record_key": f"v4:{point}:AAA", "ticker": "AAA", "as_of_at": point,
                    "feature_version": "v4", "input_hash": "old-hash",
                },
                {
                    "record_key": f"v5:{point}:BBB", "ticker": "BBB", "as_of_at": point,
                    "feature_version": "v5", "input_hash": "bbb-hash",
                },
                {
                    "record_key": f"v5:{later_point}:AAA", "ticker": "AAA", "as_of_at": later_point,
                    "feature_version": "v5", "input_hash": "late-hash",
                },
                {
                    "record_key": "v5:2025-12-31:AAA", "ticker": "AAA",
                    "as_of_at": "2025-12-31T00:00:00+00:00",
                    "feature_version": "v5", "input_hash": "outside-window",
                },
            ], key="record_key")
            store.upsert_records("rl_training_labels", [
                {
                    "record_key": f"v5:{point}:AAA", "ticker": "AAA", "as_of_at": point,
                    "feature_version": "v5", "label_id": "label-aaa",
                    "label_available_at": "2026-01-04T00:00:00+00:00",
                    "forward_return": 0.02,
                },
                {
                    "record_key": f"v5:{point}:BBB", "ticker": "BBB", "as_of_at": point,
                    "feature_version": "v5", "label_id": "label-bbb",
                    "label_available_at": "2026-01-08T00:00:00+00:00",
                },
                {
                    "record_key": f"v5:{later_point}:AAA", "ticker": "AAA", "as_of_at": later_point,
                    "feature_version": "v5", "label_id": "label-late",
                    "label_available_at": "2026-01-08T00:00:00+00:00",
                },
            ], key="record_key")

            with patch.object(store, "records", side_effect=AssertionError("full payload read")):
                result = store.training_sample_period_inputs(
                    ("AAA",), start_as_of="2026-01-01T00:00:00+00:00",
                    end_as_of="2026-01-05T00:00:00+00:00", feature_version="v5",
                    label_cutoff_at="2026-01-07T00:00:00+00:00",
                )

        self.assertEqual(
            [row["input_hash"] for row in result["snapshots"]], ["aaa-hash", "late-hash"],
        )
        self.assertEqual([row["label_id"] for row in result["labels"]], ["label-aaa"])
        self.assertNotIn("features", result["snapshots"][0])
        self.assertNotIn("forward_return", result["labels"][0])

    def test_invalid_metadata_window_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ResearchStore(Path(temporary) / "research.duckdb")
            with self.assertRaisesRegex(ValueError, "invalid training sample metadata window"):
                store.training_sample_period_inputs(
                    ("AAA",), start_as_of="2026-01-05T00:00:00+00:00",
                    end_as_of="2026-01-01T00:00:00+00:00", feature_version="v5",
                    label_cutoff_at="2026-01-07T00:00:00+00:00",
                )


if __name__ == "__main__":
    unittest.main()
