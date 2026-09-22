"""operations.harness.emergency 및 CLI 단위 테스트."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_agent.operations.commands.emergency_stop import main as cli_main
from investment_agent.execution.safety import lockdown
from investment_agent.operations.harness import emergency as harness_emergency
from investment_agent.execution.safety.lockdown import (
    REARM_CONFIRMATION_PHRASE,
    is_execution_locked_down,
    rearm_execution,
    set_execution_lockdown,
)
from investment_agent.operations.harness.emergency import (
    check_runtime_status,
    emergency_stop,
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
             patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[12345]), \
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
             patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[12345]), \
             patch("investment_agent.operations.harness.emergency._terminate_process", return_value=False):
            res = emergency_stop(state_dir=self.state_dir, kill_process=True)

        self.assertFalse(res["success"])
        self.assertFalse(res["process_killed"])
        self.assertTrue(res["durable_lockdown_set"])
        self.assertTrue(is_execution_locked_down(self.state_dir))

    def test_an_approval_listener_with_no_recorded_pid_is_still_killed(self) -> None:
        """긴급 정지가 state.json의 PID 하나만 겨누면 승인 리스너 등 여분 하네스가 살아남는다(감사 OP2-10).

        재현: 하네스 프로세스 PID는 기록됐지만, 명령줄로 확인한 실제 하네스 후보는 그것과
        무관한 프로세스(승인 리스너 등) 하나 더다 — 둘 다 꺼져야 한다.
        """
        self.store.save(HarnessState(process_id=111, process_started_at=utc_iso(),
                                     process_heartbeat_at=utc_iso(), stopped_cleanly=False, jobs={}))
        killed = []
        with patch("investment_agent.operations.harness.emergency._is_process_alive", return_value=True), \
             patch("investment_agent.operations.harness.switch._find_running_harness_pids",
                   return_value=[111, 222]), \
             patch("investment_agent.operations.harness.emergency._terminate_process",
                   side_effect=lambda pid: killed.append(pid) or True):
            res = emergency_stop(state_dir=self.state_dir, kill_process=True)
        self.assertEqual(sorted(killed), [111, 222])
        self.assertEqual(sorted(res["killed_pids"]), [111, 222])
        self.assertTrue(res["process_killed"])
        self.assertTrue(res["success"])

    def test_recorded_pid_reused_by_another_program_is_never_killed(self) -> None:
        # 재부팅 뒤 상태 파일의 PID를 다른 프로그램이 받았다. 살아 있어도 하네스가 아니면 끄지 않는다.
        self.store.save(HarnessState(process_id=12345, process_started_at=utc_iso(),
                                     process_heartbeat_at=utc_iso(), stopped_cleanly=False, jobs={}))
        with patch("investment_agent.operations.harness.emergency._is_process_alive", return_value=True), \
             patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]), \
             patch("investment_agent.operations.harness.emergency._terminate_process") as terminate:
            res = emergency_stop(state_dir=self.state_dir, kill_process=True)
        terminate.assert_not_called()
        self.assertTrue(res["durable_lockdown_set"])

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

    def test_harness_lockdown_api_is_a_compatibility_reexport(self) -> None:
        self.assertIs(harness_emergency.set_execution_lockdown, lockdown.set_execution_lockdown)
        self.assertIs(harness_emergency.is_execution_locked_down, lockdown.is_execution_locked_down)
        self.assertIs(harness_emergency.rearm_execution, lockdown.rearm_execution)

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


class EmergencyStopSignalsTest(unittest.TestCase):
    """성공 신호가 "요청한 일을 다 했는가"를 말해야 한다.

    전에는 `process_killed`가 False로 시작해서, `--lockdown-env`만 쓰고 프로세스가
    살아 있으면 잠금·상태 전이·.env 기록이 모두 성공해도 `success: False`·종료 코드 1이
    나왔다(감사 OP2-08). 그리고 `.env`를 못 찾으면 조용히 `env_locked=False`로 끝나
    운영자가 킬스위치가 잠겼다고 오해할 수 있었다(감사 OP2-09).
    """

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self._temp.name) / "ops"
        self.state_dir.mkdir(parents=True)
        self.store = JsonStateStore(self.state_dir / "state.json")
        self.store.save(HarnessState(process_id=4242, stopped_cleanly=False, jobs={}))

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_lockdown_only_is_a_success_even_with_a_live_process(self):
        root = Path(self._temp.name)
        (root / ".env").write_text("TRADING_KILL_SWITCH=off\n", encoding="utf-8")
        res = emergency_stop(
            state_dir=self.state_dir, kill_process=False,
            lockdown_env_file=True, repository_root=root,
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["env_locked"])
        self.assertIsNone(res["process_killed"])
        self.assertIn("TRADING_KILL_SWITCH=on", (root / ".env").read_text(encoding="utf-8"))

    def test_a_missing_env_file_is_an_error_not_a_quiet_false(self):
        with self.assertRaises(FileNotFoundError):
            emergency_stop(
                state_dir=self.state_dir, kill_process=False,
                lockdown_env_file=True, repository_root=Path(self._temp.name) / "nowhere",
            )

    def test_a_failed_kill_is_still_a_failure(self):
        with patch("investment_agent.operations.harness.emergency._is_process_alive", return_value=True), \
             patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[4242]), \
             patch("investment_agent.operations.harness.emergency._terminate_process", return_value=False):
            res = emergency_stop(state_dir=self.state_dir, kill_process=True)
        self.assertFalse(res["success"])
        self.assertFalse(res["process_killed"])
