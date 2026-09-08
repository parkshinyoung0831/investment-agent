"""하네스 Intelligence 잡. 한 단계 실패가 나머지를 멈추지 않는다."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from unittest.mock import patch

from investment_agent.operations.harness import pipeline
from investment_agent.operations.harness.contracts import StageContext, StageOutcome

NOW = datetime(2026, 9, 6, 3, 0, tzinfo=timezone.utc)


def _context(stage_id: str) -> StageContext:
    return StageContext(
        job_id="intelligence",
        run_id="run_intelligence",
        stage_id=stage_id,
        attempt=1,
        idempotency_key="key",
        now=NOW,
        stop_event=Event(),
        prior_metadata={},
        completed_metadata={},
    )


class IntelligenceJobTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "intelligence.duckdb"

    def test_job_has_three_independent_stages(self) -> None:
        job = pipeline.intelligence_job(database_path=self.path)
        self.assertEqual(("news", "social", "retention"), tuple(s.stage_id for s in job.stages))

    def test_social_failure_does_not_hide_news_result(self) -> None:
        with patch.object(pipeline, "_collect_news", return_value={"stored": 3}), \
             patch.object(pipeline, "_collect_social", side_effect=RuntimeError("boom")), \
             patch.object(pipeline, "_prune_intelligence", return_value={"total": 1}):
            job = pipeline.intelligence_job(database_path=self.path)
            handlers = {stage.stage_id: stage.handler for stage in job.stages}

            news_outcome = handlers["news"](_context("news"))
            social_outcome = handlers["social"](_context("social"))
            prune_outcome = handlers["retention"](_context("retention"))

        self.assertEqual(StageOutcome.succeeded({"stored": 3}), news_outcome)
        self.assertEqual("skipped", social_outcome.status)
        self.assertEqual("RuntimeError", social_outcome.metadata["error_type"])
        self.assertEqual(StageOutcome.succeeded({"total": 1}), prune_outcome)

    def test_prune_failure_does_not_hide_collection(self) -> None:
        """정리는 뒷정리다. 실패해도 그날 수집 결과를 되돌리지 않는다."""
        with patch.object(pipeline, "_collect_news", return_value={"stored": 3}), \
             patch.object(pipeline, "_collect_social", return_value={"stored": 0}), \
             patch.object(pipeline, "_prune_intelligence", side_effect=RuntimeError("boom")):
            job = pipeline.intelligence_job(database_path=self.path)
            handlers = {stage.stage_id: stage.handler for stage in job.stages}

            news_outcome = handlers["news"](_context("news"))
            social_outcome = handlers["social"](_context("social"))
            prune_outcome = handlers["retention"](_context("retention"))

        self.assertEqual(StageOutcome.succeeded({"stored": 3}), news_outcome)
        self.assertEqual(StageOutcome.succeeded({"stored": 0}), social_outcome)
        self.assertEqual("skipped", prune_outcome.status)
        self.assertEqual("RuntimeError", prune_outcome.metadata["error_type"])


if __name__ == "__main__":
    unittest.main()
