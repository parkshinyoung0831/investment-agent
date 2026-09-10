"""operations.harness.switch 및 harness_switch CLI 단위 테스트."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from investment_agent.operations.commands.harness_switch import main as cli_main
from investment_agent.operations.harness.state import HarnessState, JobRuntime, JsonStateStore, StageRuntime, utc_iso
from investment_agent.operations.harness.switch import (
    get_harness_status,
    parse_env_file,
    set_kill_switch,
    set_live_enabled,
    start_harness_service,
    stop_harness_service,
    update_env_variable,
)


class TestHarnessSwitch(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.state_dir = self.root_dir / "artifacts" / "ops" / "investment_harness"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / "state.json"
        self.store = JsonStateStore(self.state_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_get_harness_status_stopped(self) -> None:
        state = HarnessState(
            process_id=None,
            process_started_at=None,
            process_heartbeat_at=None,
            stopped_cleanly=True,
            jobs={},
        )
        self.store.save(state)

        env_file = self.root_dir / ".env"
        env_file.write_text("TRADING_KILL_SWITCH=on\nTOSS_LIVE_ENABLED=false\nAI_INVESTOR_MODE=shadow\n", encoding="utf-8")

        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]):
            status = get_harness_status(state_dir=self.state_dir, root_dir=self.root_dir)

        self.assertFalse(status.is_running)
        self.assertIsNone(status.process_id)
        self.assertTrue(status.stopped_cleanly)
        self.assertEqual(status.trading_kill_switch, "on")
        self.assertFalse(status.toss_live_enabled)
        self.assertEqual(status.ai_investor_mode, "shadow")

    def test_get_harness_status_running(self) -> None:
        state = HarnessState(
            process_id=12345,
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

        with patch("investment_agent.operations.harness.switch._is_pid_alive", return_value=True), \
             patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[12345]):
            status = get_harness_status(state_dir=self.state_dir, root_dir=self.root_dir)

        self.assertTrue(status.is_running)
        self.assertEqual(status.process_id, 12345)
        self.assertEqual(status.active_jobs_count, 1)

    def test_update_env_variable_and_parse(self) -> None:
        env_file = self.root_dir / ".env"
        env_file.write_text("TRADING_KILL_SWITCH=off\n", encoding="utf-8")

        res = set_kill_switch("on", root_dir=self.root_dir)
        self.assertTrue(res["success"])
        self.assertEqual(res["trading_kill_switch"], "on")

        parsed = parse_env_file(self.root_dir)
        self.assertEqual(parsed["TRADING_KILL_SWITCH"], "on")

        res_live = set_live_enabled(True, root_dir=self.root_dir)
        self.assertTrue(res_live["success"])
        self.assertTrue(res_live["toss_live_enabled"])

        parsed = parse_env_file(self.root_dir)
        self.assertEqual(parsed["TOSS_LIVE_ENABLED"], "true")

    def test_start_harness_service(self) -> None:
        state = HarnessState(
            process_id=None,
            stopped_cleanly=True,
            jobs={},
        )
        self.store.save(state)

        # Mock Popen to simulate background process start
        mock_proc = MagicMock()
        mock_proc.pid = 98765
        mock_proc.poll.return_value = None

        def started(*args, **kwargs):
            self.store.save(HarnessState(
                process_id=mock_proc.pid,
                process_heartbeat_at=utc_iso(),
                stopped_cleanly=False,
            ))
            return mock_proc

        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]), \
             patch("subprocess.Popen", side_effect=started):
            res = start_harness_service(
                mode="analysis_only",
                state_dir=self.state_dir,
                root_dir=self.root_dir,
                background=True,
            )

        self.assertTrue(res["success"])
        self.assertEqual(res["process_id"], 98765)
        self.assertEqual(res["mode"], "analysis_only")

    def test_start_reports_child_exit_and_keeps_diagnostics(self) -> None:
        real_popen = subprocess.Popen
        children = []

        def failing_child(argv, **kwargs):
            child = real_popen(
                [sys.executable, "-c", "import sys; sys.stderr.write('startup fixture failure\\n'); sys.exit(7)"],
                **kwargs,
            )
            children.append(child)
            return child

        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]), \
             patch("subprocess.Popen", side_effect=failing_child):
            result = start_harness_service(state_dir=self.state_dir, root_dir=self.root_dir)
        for child in children:
            child.wait(timeout=5)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "startup_failed")
        self.assertEqual(result["return_code"], 7)
        self.assertIn("startup fixture failure", Path(result["log_path"]).read_text(encoding="utf-8"))

    def test_start_does_not_accept_stale_checkpoint(self) -> None:
        self.store.save(HarnessState(process_id=111, process_heartbeat_at=utc_iso(), stopped_cleanly=False))
        child = MagicMock(pid=222)
        child.poll.return_value = None
        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]), \
             patch("investment_agent.operations.harness.switch._is_pid_alive", return_value=False), \
             patch("investment_agent.operations.harness.switch._terminate_pid", return_value=True) as terminate_tree, \
             patch("subprocess.Popen", return_value=child), \
             patch("investment_agent.operations.harness.switch.time.monotonic", side_effect=[0, 11]):
            result = start_harness_service(state_dir=self.state_dir, root_dir=self.root_dir)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "startup_timeout")
        if sys.platform == "win32":
            terminate_tree.assert_called_once_with(child.pid)
        else:
            child.terminate.assert_called_once()

    def test_start_accepts_new_checkpoint_from_virtualenv_worker(self) -> None:
        child = MagicMock(pid=222)
        child.poll.return_value = None

        def started(*args, **kwargs):
            self.store.save(HarnessState(
                process_id=333, process_started_at=utc_iso(),
                process_heartbeat_at=utc_iso(), stopped_cleanly=False,
            ))
            return child

        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]), \
             patch("investment_agent.operations.harness.switch._is_pid_alive", return_value=True), \
             patch("subprocess.Popen", side_effect=started), \
             patch("investment_agent.operations.harness.switch.time.monotonic", side_effect=[0, 11]):
            result = start_harness_service(state_dir=self.state_dir, root_dir=self.root_dir)
        self.assertTrue(result["success"])
        self.assertEqual(result["process_id"], 333)

    def test_start_harness_service_already_running(self) -> None:
        state = HarnessState(
            process_id=12345,
            stopped_cleanly=False,
            jobs={},
        )
        self.store.save(state)

        with patch("investment_agent.operations.harness.switch._is_pid_alive", return_value=True), \
             patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[12345]):
            res = start_harness_service(
                mode="analysis_only",
                state_dir=self.state_dir,
                root_dir=self.root_dir,
            )

        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "already_running")

    def test_stop_harness_service(self) -> None:
        state = HarnessState(
            process_id=12345,
            stopped_cleanly=False,
            jobs={
                "job_a": JobRuntime(
                    job_id="job_a",
                    run_id="run_1",
                    status="running",
                    scheduled_at=utc_iso(),
                    started_at=utc_iso(),
                    heartbeat_at=utc_iso(),
                    stages={},
                )
            },
        )
        self.store.save(state)

        # Create lock file
        lock_file = self.state_dir / "harness.lock"
        lock_file.write_text("lock", encoding="utf-8")
        self.assertTrue(lock_file.exists())

        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[12345]), \
             patch("investment_agent.operations.harness.switch._terminate_pid", return_value=True):
            res = stop_harness_service(state_dir=self.state_dir, root_dir=self.root_dir)

        self.assertTrue(res["success"])
        self.assertIn(12345, res["killed_pids"])
        self.assertTrue(res["lock_removed"])
        self.assertFalse(lock_file.exists())

        loaded = self.store.load()
        self.assertTrue(loaded.stopped_cleanly)
        self.assertIsNone(loaded.process_id)
        self.assertEqual(loaded.jobs["job_a"].status, "paused")

    def test_cli_flags(self) -> None:
        state = HarnessState(
            process_id=None,
            stopped_cleanly=True,
            jobs={},
        )
        self.store.save(state)

        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]):
            code_status = cli_main(["--state-dir", str(self.state_dir), "--root-dir", str(self.root_dir), "--status"])
            self.assertEqual(code_status, 0)

        code_kill = cli_main(["--state-dir", str(self.state_dir), "--root-dir", str(self.root_dir), "--kill-switch", "on"])
        self.assertEqual(code_kill, 0)

        code_live = cli_main(["--state-dir", str(self.state_dir), "--root-dir", str(self.root_dir), "--live-enabled", "false"])
        self.assertEqual(code_live, 0)

        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]):
            code_off = cli_main(["--state-dir", str(self.state_dir), "--root-dir", str(self.root_dir), "--off"])
            self.assertEqual(code_off, 0)


if __name__ == "__main__":
    unittest.main()
