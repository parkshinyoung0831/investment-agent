from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_agent.operations.control_center import control_command, dashboard_command, dashboard_url, describe_result


class DescribeResultTests(unittest.TestCase):
    """비정상 종료가 마지막 출력 줄 때문에 성공처럼 보이면 안 된다(OP-11)."""

    def test_nonzero_exit_is_shown_as_a_failure_with_the_error_line(self) -> None:
        text = describe_result(1, "하네스 정지 요청 완료\n", "Traceback...\nPermissionError: denied\n")
        self.assertIn("실패", text)
        self.assertIn("1", text)
        self.assertIn("PermissionError: denied", text)

    def test_nonzero_exit_without_output_still_says_failure(self) -> None:
        self.assertEqual(describe_result(2, "", ""), "실패(종료 코드 2)")

    def test_success_shows_the_last_stdout_line(self) -> None:
        self.assertEqual(describe_result(0, "시작 중\n하네스가 시작됐어요\n", ""), "하네스가 시작됐어요")
        self.assertEqual(describe_result(0, "", ""), "완료")


class ControlCenterTests(unittest.TestCase):
    def test_control_start_commands_reuse_launcher_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / ".venv" / "Scripts" / "python.exe"

            shadow = control_command(
                "start",
                mode="analysis_only",
                root_dir=root,
                python_path=python,
            )
            approval = control_command(
                "start",
                mode="approval_workflow",
                root_dir=root,
                python_path=python,
            )

        self.assertEqual(shadow, [str(python.resolve()), str((root / "launcher.py").resolve()), "--shadow"])
        self.assertEqual(approval[-1], "--harness")

    def test_control_stop_command_uses_single_switch_entrypoint(self) -> None:
        command = control_command("stop")

        self.assertIn("investment_agent.operations.commands.harness_switch", command)
        self.assertEqual(command[-1], "--off")

    def test_control_command_rejects_unknown_action_and_mode(self) -> None:
        with self.assertRaises(ValueError):
            control_command("kill")
        with self.assertRaises(ValueError):
            control_command("start", mode="unsupported")

    def test_dashboard_command_reuses_launcher_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / ".venv" / "Scripts" / "python.exe"

            command = dashboard_command(root_dir=root, python_path=python)

        self.assertEqual(command[0], str(python.resolve()))
        self.assertEqual(command[1], str((root / "launcher.py").resolve()))
        self.assertEqual(command[2], "--dashboard")

    @patch("investment_agent.operations.control_center.urllib.request.urlopen")
    def test_dashboard_url_returns_first_healthy_local_port(self, urlopen):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        urlopen.side_effect = [OSError("closed"), Response()]
        self.assertEqual(dashboard_url(ports=range(8501, 8503)), "http://127.0.0.1:8502")


if __name__ == "__main__":
    unittest.main()
