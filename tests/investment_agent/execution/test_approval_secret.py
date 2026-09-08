from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.execution.approval.secret import load_or_create_approval_secret
from investment_agent.execution.contracts import ExecutionSafetyError


class ApprovalSecretTest(unittest.TestCase):
    def test_explicit_secret_never_creates_a_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "unused.key"
            value = load_or_create_approval_secret({
                "DISCORD_APPROVAL_HMAC_SECRET": "x" * 40,
                "DISCORD_APPROVAL_HMAC_SECRET_FILE": str(path),
            })
            self.assertEqual(value, "x" * 40)
            self.assertFalse(path.exists())

    def test_file_secret_is_created_once_and_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "approval.key"
            env = {"DISCORD_APPROVAL_HMAC_SECRET_FILE": str(path)}
            first = load_or_create_approval_secret(env)
            second = load_or_create_approval_secret(env)
            self.assertEqual(first, second)
            self.assertEqual(path.read_text(encoding="utf-8").strip(), first)
            self.assertNotIn(first, repr(env))

    def test_short_inline_or_oversized_file_fails_closed(self):
        with self.assertRaisesRegex(ExecutionSafetyError, "invalid length"):
            load_or_create_approval_secret({"DISCORD_APPROVAL_HMAC_SECRET": "short"})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "approval.key"
            path.write_text("x" * 600, encoding="utf-8")
            with self.assertRaisesRegex(ExecutionSafetyError, "too large"):
                load_or_create_approval_secret({
                    "DISCORD_APPROVAL_HMAC_SECRET_FILE": str(path)
                })


if __name__ == "__main__":
    unittest.main()
