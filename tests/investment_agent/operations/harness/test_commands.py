from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from threading import Event

from investment_agent.operations.harness.commands import (
    CommandExecutionError,
    PythonModuleCommand,
    SubprocessModuleRunner,
)


class FakeProcess:
    def __init__(self, return_code: int):
        self.pid = 123
        self.return_code = return_code

    def poll(self):
        return self.return_code


class CommandRunnerTest(unittest.TestCase):
    def test_runs_fixed_module_with_argv_and_never_uses_shell(self):
        captured = {}

        def launch(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return FakeProcess(0)

        with tempfile.TemporaryDirectory() as temp:
            runner = SubprocessModuleRunner(
                repository_root=temp,
                python_executable=Path(temp) / "python.exe",
                allowed_modules=("investment_agent.safe.entry",),
                environ={"SAFE": "value"},
                popen=launch,
            )
            result = runner.run(
                PythonModuleCommand("investment_agent.safe.entry", ("--id", "intent_123")),
                stop_event=Event(),
            )
        self.assertEqual(result.return_code, 0)
        self.assertEqual(captured["argv"][1:3], ["-m", "investment_agent.safe.entry"])
        self.assertFalse(captured["kwargs"]["shell"])
        self.assertEqual(captured["kwargs"]["env"], {"SAFE": "value"})

    def test_disallowed_module_never_starts_and_failure_hides_arguments(self):
        launch_calls = []

        def launch(argv, **kwargs):
            launch_calls.append(argv)
            return FakeProcess(7)

        with tempfile.TemporaryDirectory() as temp:
            runner = SubprocessModuleRunner(
                repository_root=temp,
                allowed_modules=("investment_agent.safe.entry",),
                popen=launch,
            )
            with self.assertRaises(CommandExecutionError):
                runner.run(
                    PythonModuleCommand("investment_agent.unsafe.entry"),
                    stop_event=Event(),
                )
            self.assertEqual(launch_calls, [])
            with self.assertRaises(CommandExecutionError) as raised:
                runner.run(
                    PythonModuleCommand("investment_agent.safe.entry", ("secret-value",)),
                    stop_event=Event(),
                )
        self.assertNotIn("secret-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
