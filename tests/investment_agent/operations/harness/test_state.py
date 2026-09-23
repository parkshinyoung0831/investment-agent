from __future__ import annotations

import tempfile
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from unittest.mock import patch
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
    def test_overlapping_saves_do_not_share_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp:
            store = JsonStateStore(Path(temp) / "state.json")
            barrier = Barrier(2)
            original_write = Path.write_text
            original_replace = os.replace
            replaced = Event()
            sequence_lock = Lock()
            calls = []

            def overlapping_write(path, *args, **kwargs):
                result = original_write(path, *args, **kwargs)
                barrier.wait(timeout=5)
                return result

            def ordered_replace(source, target):
                with sequence_lock:
                    calls.append(source)
                    is_first = len(calls) == 1
                if is_first:
                    try:
                        return original_replace(source, target)
                    finally:
                        replaced.set()
                self.assertTrue(replaced.wait(timeout=5))
                return original_replace(source, target)

            with patch.object(Path, "write_text", overlapping_write), \
                 patch("investment_agent.operations.harness.state.os.replace", ordered_replace), \
                 ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(store.save, running_state()) for _ in range(2)]
                for future in futures:
                    future.result(timeout=10)
            self.assertEqual(store.load().jobs["investment_pipeline"].run_id, "run_one")
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])

    def test_temporary_replace_permission_error_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            store = JsonStateStore(Path(temp) / "state.json")
            replace = os.replace
            attempts = []

            def temporarily_locked(source, target):
                attempts.append(source)
                if len(attempts) < 3:
                    raise PermissionError("sharing violation")
                return replace(source, target)

            with patch("investment_agent.operations.harness.state.os.replace", temporarily_locked):
                store.save(running_state())
            self.assertEqual(len(attempts), 3)
            self.assertEqual(store.load().jobs["investment_pipeline"].run_id, "run_one")

    def test_a_read_during_another_process_replace_waits_instead_of_failing(self):
        """실행 중인 하네스가 파일을 교체하는 찰나의 읽기 거절 때문에 기동이 "시작 실패"로 보고됐다."""
        with tempfile.TemporaryDirectory() as temp:
            store = JsonStateStore(Path(temp) / "state.json")
            store.save(running_state())
            read_text = Path.read_text
            attempts = []

            def temporarily_locked(path, *args, **kwargs):
                attempts.append(path)
                if len(attempts) < 3:
                    raise PermissionError(13, "Permission denied")
                return read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", temporarily_locked):
                loaded = store.load()
            self.assertEqual(3, len(attempts))
            self.assertEqual("run_one", loaded.jobs["investment_pipeline"].run_id)

    def test_a_persistent_read_permission_error_is_still_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            store = JsonStateStore(Path(temp) / "state.json")
            store.save(running_state())
            with patch.object(Path, "read_text", side_effect=PermissionError(13, "Permission denied")):
                with self.assertRaises(StateCorruptionError):
                    store.load()

    def test_persistent_replace_permission_error_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            store = JsonStateStore(Path(temp) / "state.json")
            store.save(running_state())
            original = store.path.read_bytes()
            with patch("investment_agent.operations.harness.state.os.replace", side_effect=PermissionError("locked")) as replace:
                with self.assertRaises(PermissionError):
                    store.save(HarnessState())
            self.assertLessEqual(replace.call_count, 6)
            self.assertEqual(store.path.read_bytes(), original)
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])

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
