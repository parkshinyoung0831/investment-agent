"""Decision experience의 최초 관측 보존과 label cutoff read 계약."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from investment_agent.research.storage.repository import ResearchStore


class DecisionExperienceStorageTest(unittest.TestCase):
    def test_first_observation_is_preserved_and_future_labels_are_cut_off(self):
        first = {
            "record_key": "c", "case_key": "c", "ticker": "ABC",
            "as_of_at": "2026-01-01T00:00:00+00:00",
            "available_at": "2026-01-08T00:00:00+00:00", "net_reward": 0.04,
        }
        with tempfile.TemporaryDirectory() as temporary:
            store = ResearchStore(Path(temporary) / "research.duckdb")
            store.save_decision_experiences([first])
            store.save_decision_experiences([{**first, "net_reward": 99}])

            self.assertEqual(store.decision_experience_rows(), [first])
            self.assertEqual(store.decision_experience_rows(
                as_of_at=datetime(2026, 1, 7, tzinfo=timezone.utc),
            ), [])
            self.assertEqual(store.decision_experience_rows(
                as_of_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
            ), [first])


if __name__ == "__main__":
    unittest.main()
