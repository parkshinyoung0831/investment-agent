from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from investment_agent.operations.harness.state import (
    HarnessState,
    JobRuntime,
    JsonStateStore,
    StageRuntime,
    StateCorruptionError,
    recover_interrupted_jobs,
)

UTC = timezone.utc


def running_state() -> HarnessState:
    timestamp = "2026-08-22T00:00:00+00:00"
    return HarnessState(
        stopped_cleanly=False,
        process_heartbeat_at=timestamp,
        jobs={
            "investment_pipeline": JobRuntime(
                job_id="investment_pipeline",
                run_id="run_one",
                status="running",
                scheduled_at=timestamp,
                started_at=timestamp,
                heartbeat_at=timestamp,
                stage="analysis",
                stages={"analysis": StageRuntime(status="running", attempts=1)},
            )
        },
    )


class HarnessStateTest(unittest.TestCase):
    def test_round_trip_and_recovery_preserve_run_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            store = JsonStateStore(Path(temp) / "state.json")
            store.save(running_state())
            loaded = store.load()
            recovered = recover_interrupted_jobs(
                loaded,
                now=datetime(2026, 8, 22, 0, 5, tzinfo=UTC),
            )
            self.assertEqual(recovered, ("investment_pipeline",))
            job = loaded.jobs["investment_pipeline"]
            self.assertEqual(job.run_id, "run_one")
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.stages["analysis"].status, "pending")
            self.assertEqual(loaded.recovery_count, 1)

    def test_corrupt_checkpoint_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(StateCorruptionError):
                JsonStateStore(path).load()

    def test_metadata_secret_keys_are_redacted_before_write(self):
        with tempfile.TemporaryDirectory() as temp:
            state = running_state()
            state.jobs["investment_pipeline"].stages["analysis"].metadata = {
                "api_key": "do-not-store",
                "safe": "value",
            }
            store = JsonStateStore(Path(temp) / "state.json")
            store.save(state)
            text = store.path.read_text(encoding="utf-8")
            self.assertNotIn("do-not-store", text)
            self.assertIn("[REDACTED]", text)


if __name__ == "__main__":
    unittest.main()
