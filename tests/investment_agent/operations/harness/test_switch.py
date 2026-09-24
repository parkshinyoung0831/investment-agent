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
    ALLOW_ORDERS_CONFIRMATION,
    ENABLE_LIVE_CONFIRMATION,
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

    def test_mode_is_the_recorded_startup_mode_not_recomputed_from_env(self) -> None:
        """`.env`가 실행 중 프로세스에 반영되지 않아도, 상태창이 실제 기동 모드를 말해야 한다(감사 OP2-07).

        재현: analysis_only로 뜬 프로세스인데 `.env`는 나중에 approval_workflow 조건으로 바뀐 경우다.
        """
        state = HarnessState(process_id=12345, mode="analysis_only", jobs={})
        self.store.save(state)
        env_file = self.root_dir / ".env"
        env_file.write_text("TRADING_KILL_SWITCH=off\nTOSS_LIVE_ENABLED=true\n", encoding="utf-8")

        with patch("investment_agent.operations.harness.switch._is_pid_alive", return_value=True), \
             patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[12345]):
            status = get_harness_status(state_dir=self.state_dir, root_dir=self.root_dir)

        self.assertEqual(status.mode, "analysis_only")
        # env만 보면 승인 흐름이 켜진 것처럼 읽힌다 — 실제 모드와 다르다는 사실이 남아야 한다.
        self.assertEqual(status.mode_would_be, "approval_workflow")

    def test_mode_is_none_before_the_harness_has_ever_started(self) -> None:
        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]):
            status = get_harness_status(state_dir=self.state_dir, root_dir=self.root_dir)
        self.assertIsNone(status.mode)

    def test_status_and_stop_ignore_a_recorded_pid_that_is_not_the_harness(self) -> None:
        from investment_agent.operations.harness.switch import stop_harness_service

        state = self.store.load()
        state.process_id = 3256
        self.store.save(state)
        with patch("investment_agent.operations.harness.switch._is_pid_alive", return_value=True), \
             patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]), \
             patch("investment_agent.operations.harness.switch._terminate_pid") as terminate:
            status = get_harness_status(state_dir=self.state_dir, root_dir=self.root_dir)
            result = stop_harness_service(state_dir=self.state_dir)
        self.assertFalse(status.is_running)
        terminate.assert_not_called()
        self.assertEqual(result["stale_recorded_pid"], 3256)

    def test_stop_kills_only_verified_harness_processes(self) -> None:
        from investment_agent.operations.harness.switch import stop_harness_service

        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[777]), \
             patch("investment_agent.operations.harness.switch._terminate_pid", return_value=True) as terminate:
            result = stop_harness_service(state_dir=self.state_dir)
        terminate.assert_called_once_with(777)
        self.assertEqual(result["killed_pids"], [777])

    def test_update_env_variable_and_parse(self) -> None:
        env_file = self.root_dir / ".env"
        env_file.write_text("TRADING_KILL_SWITCH=off\n", encoding="utf-8")

        res = set_kill_switch("on", root_dir=self.root_dir)
        self.assertTrue(res["success"])
        self.assertEqual(res["trading_kill_switch"], "on")

        parsed = parse_env_file(self.root_dir)
        self.assertEqual(parsed["TRADING_KILL_SWITCH"], "on")

        res_live = set_live_enabled(
            True, root_dir=self.root_dir, confirm=ENABLE_LIVE_CONFIRMATION,
        )
        self.assertTrue(res_live["success"])
        self.assertTrue(res_live["toss_live_enabled"])

        parsed = parse_env_file(self.root_dir)
        self.assertEqual(parsed["TOSS_LIVE_ENABLED"], "true")

    def test_one_trading_switch_moves_both_gates_together(self) -> None:
        """사람이 쓰는 스위치는 하나다. 킬스위치와 실매매 플래그가 따로 놀지 않는다."""
        from investment_agent.operations.harness.switch import START_TRADING_CONFIRMATION, set_trading

        (self.root_dir / ".env").write_text("TRADING_KILL_SWITCH=on\nTOSS_LIVE_ENABLED=false\n", encoding="utf-8")
        refused = set_trading(True, root_dir=self.root_dir, state_dir=self.state_dir)
        self.assertFalse(refused["success"])
        self.assertEqual(("on", "false"), (parse_env_file(self.root_dir)["TRADING_KILL_SWITCH"],
                                           parse_env_file(self.root_dir)["TOSS_LIVE_ENABLED"]))

        armed = set_trading(True, root_dir=self.root_dir, state_dir=self.state_dir, confirm=START_TRADING_CONFIRMATION)
        self.assertTrue(armed["success"])
        self.assertEqual(("off", "true"), (parse_env_file(self.root_dir)["TRADING_KILL_SWITCH"],
                                           parse_env_file(self.root_dir)["TOSS_LIVE_ENABLED"]))

        disarmed = set_trading(False, root_dir=self.root_dir, state_dir=self.state_dir)
        self.assertTrue(disarmed["success"])
        self.assertEqual(("on", "false"), (parse_env_file(self.root_dir)["TRADING_KILL_SWITCH"],
                                           parse_env_file(self.root_dir)["TOSS_LIVE_ENABLED"]))

    def test_the_trading_switch_refuses_to_arm_during_an_emergency_lockdown(self) -> None:
        from investment_agent.execution.safety.lockdown import get_lockdown_path
        from investment_agent.operations.harness.switch import START_TRADING_CONFIRMATION, set_trading

        (self.root_dir / ".env").write_text("TRADING_KILL_SWITCH=on\nTOSS_LIVE_ENABLED=false\n", encoding="utf-8")
        lockdown = get_lockdown_path(self.state_dir)
        lockdown.parent.mkdir(parents=True, exist_ok=True)
        lockdown.write_text("{}", encoding="utf-8")
        result = set_trading(True, root_dir=self.root_dir, state_dir=self.state_dir, confirm=START_TRADING_CONFIRMATION)
        self.assertFalse(result["success"])
        self.assertIn("lockdown", result["message"])
        self.assertEqual("on", parse_env_file(self.root_dir)["TRADING_KILL_SWITCH"])

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


class GateConfirmationTest(unittest.TestCase):
    """주문을 허용하는 방향으로 게이트를 바꿀 때만 확인 문구를 요구한다.

    CLAUDE.md의 첫 "하지 말 것"이 이 게이트다. 전에는 `--live-enabled true` 한 줄이나
    대화형 메뉴의 Enter 두 번으로 바뀌었고 확인 문구가 없었다. 문구를 요구하는 자리는
    진입점이 아니라 setter다 — 진입점에 두면 새 진입점에서 빠뜨린다.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        (self.root_dir / ".env").write_text(
            "TRADING_KILL_SWITCH=on\nTOSS_LIVE_ENABLED=false\n", encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _env(self) -> dict[str, str]:
        return parse_env_file(self.root_dir)

    def test_allowing_orders_without_the_phrase_changes_nothing(self) -> None:
        result = set_kill_switch("off", root_dir=self.root_dir)
        self.assertFalse(result["success"])
        self.assertFalse(result["changed"])
        self.assertIn(ALLOW_ORDERS_CONFIRMATION, result["message"])
        # 거절하고도 파일을 쓰면 거절한 의미가 없다.
        self.assertEqual(self._env()["TRADING_KILL_SWITCH"], "on")

    def test_a_wrong_phrase_is_not_accepted(self) -> None:
        result = set_kill_switch("off", root_dir=self.root_dir, confirm="yes")
        self.assertFalse(result["success"])
        self.assertEqual(self._env()["TRADING_KILL_SWITCH"], "on")

    def test_allowing_orders_with_the_phrase_applies(self) -> None:
        result = set_kill_switch(
            "off", root_dir=self.root_dir, confirm=ALLOW_ORDERS_CONFIRMATION,
        )
        self.assertTrue(result["success"])
        self.assertEqual(self._env()["TRADING_KILL_SWITCH"], "off")

    def test_blocking_orders_needs_no_phrase(self) -> None:
        """막는 방향은 안전 방향이다 — 급할 때 문구를 몰라 못 막으면 더 나쁘다."""
        set_kill_switch("off", root_dir=self.root_dir, confirm=ALLOW_ORDERS_CONFIRMATION)
        result = set_kill_switch("on", root_dir=self.root_dir)
        self.assertTrue(result["success"])
        self.assertEqual(self._env()["TRADING_KILL_SWITCH"], "on")

    def test_enabling_live_trading_without_the_phrase_changes_nothing(self) -> None:
        result = set_live_enabled(True, root_dir=self.root_dir)
        self.assertFalse(result["success"])
        self.assertFalse(result["changed"])
        self.assertIn(ENABLE_LIVE_CONFIRMATION, result["message"])
        self.assertEqual(self._env()["TOSS_LIVE_ENABLED"], "false")

    def test_enabling_live_trading_with_the_phrase_applies(self) -> None:
        result = set_live_enabled(
            True, root_dir=self.root_dir, confirm=ENABLE_LIVE_CONFIRMATION,
        )
        self.assertTrue(result["success"])
        self.assertEqual(self._env()["TOSS_LIVE_ENABLED"], "true")

    def test_disabling_live_trading_needs_no_phrase(self) -> None:
        set_live_enabled(True, root_dir=self.root_dir, confirm=ENABLE_LIVE_CONFIRMATION)
        result = set_live_enabled(False, root_dir=self.root_dir)
        self.assertTrue(result["success"])
        self.assertEqual(self._env()["TOSS_LIVE_ENABLED"], "false")

    def test_the_two_phrases_are_different(self) -> None:
        """같은 문구면 하나를 외운 사람이 둘 다 열 수 있다."""
        self.assertNotEqual(ALLOW_ORDERS_CONFIRMATION, ENABLE_LIVE_CONFIRMATION)

    def _cli(self, *arguments: str) -> int:
        return cli_main(["--root-dir", str(self.root_dir), *arguments])

    def test_the_cli_refuses_to_enable_live_without_the_phrase(self) -> None:
        """진입점이 setter의 거절을 종료 코드로 그대로 옮겨야 한다."""
        with patch("sys.stdout", new=io.StringIO()):
            code = self._cli("--live-enabled", "true")
        self.assertEqual(code, 1)
        self.assertEqual(self._env()["TOSS_LIVE_ENABLED"], "false")

    def test_the_cli_enables_live_with_the_phrase(self) -> None:
        with patch("sys.stdout", new=io.StringIO()):
            code = self._cli("--live-enabled", "true", "--confirm", ENABLE_LIVE_CONFIRMATION)
        self.assertEqual(code, 0)
        self.assertEqual(self._env()["TOSS_LIVE_ENABLED"], "true")

    def test_the_cli_refuses_to_allow_orders_without_the_phrase(self) -> None:
        with patch("sys.stdout", new=io.StringIO()):
            code = self._cli("--kill-switch", "off")
        self.assertEqual(code, 1)
        self.assertEqual(self._env()["TRADING_KILL_SWITCH"], "on")


if __name__ == "__main__":
    unittest.main()
