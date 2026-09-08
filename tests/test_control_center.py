from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_agent.operations.control_center import control_command, dashboard_command, dashboard_url


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
