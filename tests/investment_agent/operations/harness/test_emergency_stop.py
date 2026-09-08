"""operations.harness.emergency 및 CLI 단위 테스트."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_agent.operations.commands.emergency_stop import main as cli_main
from investment_agent.operations.harness.emergency import (
    REARM_CONFIRMATION_PHRASE,
    check_runtime_status,
    emergency_stop,
    is_execution_locked_down,
    rearm_execution,
    set_execution_lockdown,
)
from investment_agent.operations.harness.state import HarnessState, JobRuntime, JsonStateStore, StageRuntime, utc_iso


class TestEmergencyStop(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp_dir.name)
        self.state_path = self.state_dir / "state.json"
        self.store = JsonStateStore(self.state_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_check_runtime_status(self) -> None:
        state = HarnessState(
            process_id=999999,
            process_started_at=utc_iso(),
            process_heartbeat_at=utc_iso(),
            stopped_cleanly=False,
            jobs={
                "job_a": JobRuntime(
                    job_id="job_a",
                    run_id="run_1",
                    status="running",
                    scheduled_at=utc_iso(),
                    started_at=utc_iso(),
                    heartbeat_at=utc_iso(),
                    stages={"stage_1": StageRuntime(status="running")},
                )
            },
        )
        self.store.save(state)

        status = check_runtime_status(
            state_dir=self.state_dir,
            environ={"TRADING_KILL_SWITCH": "on"},
        )
        self.assertEqual(status["process_id"], 999999)
        self.assertFalse(status["stopped_cleanly"])
        self.assertEqual(status["trading_kill_switch"], "on")
        self.assertFalse(status["execution_lockdown"])
        self.assertEqual(status["active_jobs_count"], 1)

    def test_emergency_stop_creates_durable_lockdown_and_transitions_jobs(self) -> None:
        state = HarnessState(
            process_id=12345,
            process_started_at=utc_iso(),
            process_heartbeat_at=utc_iso(),
            stopped_cleanly=False,
            jobs={
                "job_1": JobRuntime(
                    job_id="job_1",
                    run_id="run_1",
                    status="running",
                    scheduled_at=utc_iso(),
                    started_at=utc_iso(),
                    heartbeat_at=utc_iso(),
                    stages={"stage_1": StageRuntime(status="running")},
                )
            },
        )
        self.store.save(state)

        # process kill is mocked as successful
        with patch("investment_agent.operations.harness.emergency._is_process_alive", return_value=True), \
             patch("investment_agent.operations.harness.emergency._terminate_process", return_value=True):
            res = emergency_stop(state_dir=self.state_dir, kill_process=True)

        self.assertTrue(res["success"])
        self.assertTrue(res["process_killed"])
        self.assertTrue(res["durable_lockdown_set"])
        self.assertTrue(res["state_updated"])
        self.assertTrue(is_execution_locked_down(self.state_dir))

        loaded = self.store.load()
        self.assertFalse(loaded.stopped_cleanly)
        self.assertIsNone(loaded.process_id)
        self.assertEqual(loaded.jobs["job_1"].status, "paused")
        self.assertEqual(loaded.jobs["job_1"].pause_reason, "emergency_lockdown")

    def test_emergency_stop_kill_failure_returns_success_false(self) -> None:
        state = HarnessState(
            process_id=12345,
            process_started_at=utc_iso(),
            process_heartbeat_at=utc_iso(),
            stopped_cleanly=False,
            jobs={},
        )
        self.store.save(state)

        # process kill fails
        with patch("investment_agent.operations.harness.emergency._is_process_alive", return_value=True), \
             patch("investment_agent.operations.harness.emergency._terminate_process", return_value=False):
            res = emergency_stop(state_dir=self.state_dir, kill_process=True)

        self.assertFalse(res["success"])
        self.assertFalse(res["process_killed"])
        self.assertTrue(res["durable_lockdown_set"])
        self.assertTrue(is_execution_locked_down(self.state_dir))

    def test_rearm_execution(self) -> None:
        set_execution_lockdown(state_dir=self.state_dir, reason="test")
        self.assertTrue(is_execution_locked_down(self.state_dir))

        # Re-arm with invalid confirmation fails
        with self.assertRaises(ValueError):
            rearm_execution(state_dir=self.state_dir, confirmation="wrong")

        self.assertTrue(is_execution_locked_down(self.state_dir))

        # Re-arm with valid confirmation succeeds
        unlocked = rearm_execution(state_dir=self.state_dir, confirmation=REARM_CONFIRMATION_PHRASE)
        self.assertTrue(unlocked)
        self.assertFalse(is_execution_locked_down(self.state_dir))

    def test_emergency_stop_lockdown_env_file(self) -> None:
        dummy_repo = self.state_dir / "repo"
        dummy_repo.mkdir()
        env_file = dummy_repo / ".env"
        env_file.write_text("TRADING_KILL_SWITCH=off\nTOSS_LIVE_ENABLED=true\n", encoding="utf-8")

        res = emergency_stop(
            state_dir=self.state_dir,
            kill_process=False,
            lockdown_env_file=True,
            repository_root=dummy_repo,
        )
        self.assertTrue(res["env_locked"])
        new_env = env_file.read_text(encoding="utf-8")
        self.assertIn("TRADING_KILL_SWITCH=on", new_env)

    def test_cli_rearm(self) -> None:
        set_execution_lockdown(state_dir=self.state_dir, reason="test")
        self.assertTrue(is_execution_locked_down(self.state_dir))

        # CLI rearm without confirm fails
        code = cli_main(["--state-dir", str(self.state_dir), "--rearm"])
        self.assertEqual(code, 1)
        self.assertTrue(is_execution_locked_down(self.state_dir))

        # CLI rearm with correct confirm succeeds
        code = cli_main([
            "--state-dir", str(self.state_dir),
            "--rearm",
            "--confirm", REARM_CONFIRMATION_PHRASE,
        ])
        self.assertEqual(code, 0)
        self.assertFalse(is_execution_locked_down(self.state_dir))


if __name__ == "__main__":
    unittest.main()
