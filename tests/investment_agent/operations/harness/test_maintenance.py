"""정비 보류(maintenance hold) — 코드를 고치는 동안 하네스가 뜨지 않는지 검증한다.

킬스위치는 **뜬 뒤에** 주문만 막는다. 정비 중에 프로세스가 뜨면 분석 잡이 돌고
상태 파일이 갱신돼 작업 중인 코드와 섞인다. 여기서 지키는 것은 그 앞 단계다.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from investment_agent.operations.commands.harness_switch import main as cli_main
from investment_agent.operations.harness.emergency import is_execution_locked_down, set_execution_lockdown
from investment_agent.operations.harness.maintenance import (
    MAINTENANCE_SENTINEL_FILENAME,
    clear_maintenance_hold,
    is_maintenance_held,
    read_maintenance_hold,
    set_maintenance_hold,
)
from investment_agent.operations.harness.state import HarnessState, JsonStateStore, utc_iso
from investment_agent.operations.harness.switch import get_harness_status, start_harness_service


class MaintenanceHoldTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.state_dir = self.root_dir / "artifacts" / "ops" / "investment_harness"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        JsonStateStore(self.state_dir / "state.json").save(
            HarnessState(process_id=None, stopped_cleanly=True, jobs={})
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _start(self):
        child = MagicMock(pid=4242)
        child.poll.return_value = None

        def started(*args, **kwargs):
            JsonStateStore(self.state_dir / "state.json").save(HarnessState(
                process_id=child.pid, process_heartbeat_at=utc_iso(), stopped_cleanly=False,
            ))
            return child

        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]), \
             patch("subprocess.Popen", side_effect=started) as popen:
            result = start_harness_service(
                mode="analysis_only",
                state_dir=self.state_dir,
                root_dir=self.root_dir,
                background=True,
            )
        return result, popen

    def test_hold_is_absent_by_default(self) -> None:
        self.assertFalse(is_maintenance_held(self.state_dir))
        self.assertIsNone(read_maintenance_hold(self.state_dir))

    def test_sentinel_records_reason_and_time(self) -> None:
        path = set_maintenance_hold(state_dir=self.state_dir, reason="db_rebuild")

        self.assertEqual(path.name, MAINTENANCE_SENTINEL_FILENAME)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["reason"], "db_rebuild")
        self.assertTrue(payload["held_at"])
        self.assertTrue(payload["hold_id"].startswith("hold_"))

    def test_start_is_refused_while_held(self) -> None:
        set_maintenance_hold(state_dir=self.state_dir, reason="db_rebuild")

        result, popen = self._start()

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "maintenance_hold")
        self.assertIn("db_rebuild", result["message"])
        popen.assert_not_called()  # 프로세스가 아예 뜨지 않아야 한다

    def test_start_works_again_once_cleared(self) -> None:
        set_maintenance_hold(state_dir=self.state_dir, reason="db_rebuild")
        self.assertTrue(clear_maintenance_hold(self.state_dir))

        result, popen = self._start()

        self.assertTrue(result["success"])
        popen.assert_called_once()

    def test_clearing_hold_leaves_execution_lockdown_alone(self) -> None:
        """정비 해제가 거래 잠금까지 같이 푸는 사고를 막는다."""
        set_execution_lockdown(state_dir=self.state_dir, reason="emergency_stop")
        set_maintenance_hold(state_dir=self.state_dir, reason="db_rebuild")

        clear_maintenance_hold(self.state_dir)

        self.assertFalse(is_maintenance_held(self.state_dir))
        self.assertTrue(is_execution_locked_down(self.state_dir))

    def test_status_surfaces_the_hold(self) -> None:
        set_maintenance_hold(state_dir=self.state_dir, reason="db_rebuild")

        with patch("investment_agent.operations.harness.switch._find_running_harness_pids", return_value=[]):
            status = get_harness_status(state_dir=self.state_dir, root_dir=self.root_dir)

        self.assertTrue(status.maintenance_hold)
        self.assertEqual(status.maintenance_reason, "db_rebuild")

    def test_corrupted_sentinel_still_blocks(self) -> None:
        """읽을 수 없는 sentinel을 '보류 아님'으로 해석하면 정비 중에 하네스가 뜬다."""
        path = self.state_dir / MAINTENANCE_SENTINEL_FILENAME
        path.write_text("{ this is not json", encoding="utf-8")

        self.assertTrue(is_maintenance_held(self.state_dir))
        self.assertEqual(read_maintenance_hold(self.state_dir), {"error": "corrupted_maintenance_file"})
        result, popen = self._start()
        self.assertFalse(result["success"])
        popen.assert_not_called()


class MaintenanceCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.state_dir = self.root_dir / "artifacts" / "ops" / "investment_harness"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _cli(self, *args: str) -> int:
        return cli_main([
            *args,
            "--state-dir", str(self.state_dir),
            "--root-dir", str(self.root_dir),
        ])

    def test_cli_sets_and_clears_the_hold(self) -> None:
        self.assertEqual(self._cli("--maintenance", "on", "--maintenance-reason", "cli_test"), 0)
        self.assertTrue(is_maintenance_held(self.state_dir))
        self.assertEqual((read_maintenance_hold(self.state_dir) or {})["reason"], "cli_test")

        self.assertEqual(self._cli("--maintenance", "off"), 0)
        self.assertFalse(is_maintenance_held(self.state_dir))

    def test_clearing_an_absent_hold_is_not_an_error(self) -> None:
        self.assertEqual(self._cli("--maintenance", "off"), 0)


if __name__ == "__main__":
    unittest.main()
