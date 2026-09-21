"""Research 원장의 key-only 조회가 payload 파싱 없이 기존 정체성을 반환한다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.research.storage.repository import ResearchStore


class RecordKeysTest(unittest.TestCase):
    def test_record_keys_return_the_existing_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ResearchStore(Path(temporary) / "research.duckdb")
            self.assertEqual(store.record_keys("training_samples"), set())
            store.upsert_records("training_samples", [
                {"record_key": "sample-a", "as_of_at": "2025-01-03T23:30:00+00:00", "ticker": "AAPL"},
                {"record_key": "sample-b", "as_of_at": "2025-01-03T23:30:00+00:00", "ticker": "MSFT"},
            ], key="record_key")
            self.assertEqual(store.record_keys("training_samples"), {"sample-a", "sample-b"})

    def test_payload_field_projection_avoids_decoding_unrequested_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ResearchStore(Path(temporary) / "research.duckdb")
            store.upsert_records("rl_feature_snapshots", [{
                "record_key": "2026-01-02T00:00:00+00:00:AAA",
                "ticker": "AAA",
                "as_of_at": "2026-01-02T00:00:00+00:00",
                "input_hash": "input-123",
                "features": {"large_payload": [1, 2, 3]},
            }], key="record_key")

            rows = store.records_with_payload_fields(
                "rl_feature_snapshots", ("input_hash",),
            )

            self.assertEqual(rows, [{
                "record_key": "2026-01-02T00:00:00+00:00:AAA",
                "ticker": "AAA",
                "as_of_at": "2026-01-02T00:00:00+00:00",
                "available_at": None,
                "input_hash": "input-123",
            }])

if __name__ == "__main__":
    unittest.main()
