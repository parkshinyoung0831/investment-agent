from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.operations.commands.approval_listener_service import main
from investment_agent.operations.harness.lock import ProcessFileLock


class ApprovalListenerServiceTest(unittest.TestCase):
    def test_listener_uses_its_own_lock_and_releases_after_exit(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(
                main(["--state-dir", temp], listener=lambda: calls.append("run") or 0),
                0,
            )
            self.assertEqual(calls, ["run"])
            with ProcessFileLock(Path(temp) / "approval_listener.lock"):
                pass

    def test_duplicate_listener_never_starts_second_gateway(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            with ProcessFileLock(Path(temp) / "approval_listener.lock"):
                result = main(
                    ["--state-dir", temp],
                    listener=lambda: calls.append("run") or 0,
                )
            self.assertEqual(result, 2)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
