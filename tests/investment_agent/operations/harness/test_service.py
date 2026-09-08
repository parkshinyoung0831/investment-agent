from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from investment_agent.operations.harness.contracts import JobDefinition, StageDefinition, StageOutcome
from investment_agent.operations.harness.lock import ProcessFileLock
from investment_agent.operations.harness.runtime import HarnessScheduler, JobRegistry
from investment_agent.operations.harness.service import HarnessService
from investment_agent.operations.harness.state import JsonStateStore

UTC = timezone.utc


class FakeReporter:
    def event(self, event_type: str, **fields):
        pass

    def error(self, event_type: str, **fields):
        pass


class HarnessServiceTest(unittest.TestCase):
    def test_run_once_checkpoints_clean_shutdown_and_releases_lock(self):
        moment = datetime(2026, 8, 22, tzinfo=UTC)

        def handler(context):
            return StageOutcome.succeeded()

        registry = JobRegistry()
        registry.register(JobDefinition(
            job_id="analysis",
            stages=(StageDefinition("prepare", handler),),
            interval_seconds=60,
        ))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            store = JsonStateStore(path / "state.json")
            reporter = FakeReporter()
            scheduler = HarnessScheduler(
                registry=registry, store=store, environ={}, reporter=reporter,
            )
            service = HarnessService(
                scheduler=scheduler,
                lock=ProcessFileLock(path / "harness.lock"),
                now=lambda: moment,
                reporter=reporter,
            )
            self.assertEqual(service.run_once(), 0)
            state = store.load()
            self.assertTrue(state.stopped_cleanly)
            self.assertEqual(state.jobs["analysis"].status, "succeeded")
            with ProcessFileLock(path / "harness.lock"):
                pass


if __name__ == "__main__":
    unittest.main()
