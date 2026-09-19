"""Trading reader cache·원장·Research artifact 저장소의 소유권을 고정한다."""
from __future__ import annotations

import inspect
import unittest


class RepositoryOwnershipTest(unittest.TestCase):
    def test_point_in_time_cache_is_not_kept_on_the_compatibility_facade(self) -> None:
        from investment_agent.trading.supabase_repository import (
            PointInTimeReaderCache,
            SupabaseRepository,
        )

        self.assertIn("_memo_state", inspect.getsource(PointInTimeReaderCache))
        self.assertNotIn("_memo_state", inspect.getsource(SupabaseRepository._memo))

    def test_research_store_owns_recalculable_artifact_writes(self) -> None:
        from investment_agent.research.storage.repository import ResearchStore

        self.assertTrue({
            "save_events",
            "save_event_features",
            "save_training_samples",
            "save_training_sample_runs",
            "save_rl_feature_snapshots",
            "save_rl_training_labels",
            "save_valuation_observations",
            "save_decision_experiences",
            "model_evaluation_rows",
            "model_evaluation_summary",
            "save_promotion",
            "approve_model_promotion",
        } <= set(dir(ResearchStore)))


if __name__ == "__main__":
    unittest.main()
