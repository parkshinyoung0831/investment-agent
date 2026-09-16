"""동일한 학습 표본 재실행이 연구 Parquet를 다시 쓰지 않는지 확인한다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_agent.research.datasets.contracts import TrainingSample
from investment_agent.research.storage.repository import ResearchStore
from investment_agent.trading.supabase_repository import SupabaseRepository


class TrainingSamplePersistenceTest(unittest.TestCase):
    def test_identical_sample_keeps_the_existing_parquet_file(self):
        sample = TrainingSample(
            sample_id="", ticker="AAPL", as_of_at="2025-01-03T23:30:00+00:00",
            label_available_at="2025-02-03T21:00:00+00:00", feature_version="v5",
            label_definition="net_excess_return", features={"price_return_20d": 0.02},
            labels={"net_excess_return": 0.01}, provenance={"source": "shadow_simulation"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            store = ResearchStore(Path(temporary) / "research.duckdb")
            with patch("investment_agent.trading.supabase_repository.ResearchStore", return_value=store):
                repository = SupabaseRepository()
                first = repository.save_training_samples([sample])
                parquet = store._dataset_root("training_samples") / "year=2025" / "data.parquet"
                before = parquet.read_bytes()
                before_mtime = parquet.stat().st_mtime_ns
                with patch.object(store, "upsert_records", side_effect=RuntimeError("writer unavailable")):
                    second = repository.save_training_samples([sample])
                after = parquet.read_bytes()
                after_mtime = parquet.stat().st_mtime_ns

            self.assertEqual(first, 1)
            self.assertEqual(second, 0)
            self.assertEqual(after, before)
            self.assertEqual(after_mtime, before_mtime)
            self.assertEqual(len(store.records("training_samples")), 1)


if __name__ == "__main__":
    unittest.main()
