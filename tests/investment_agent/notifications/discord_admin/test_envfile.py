""".env 갱신 — 비밀값 파일을 다루므로 손실이 나면 안 된다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.notifications.discord_admin import envfile


class EnvFileTest(unittest.TestCase):
    def _write(self, text: str) -> Path:
        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text(text, encoding="utf-8")
        return path

    def test_existing_key_is_replaced_in_place(self):
        path = self._write("A=1\nDISCORD_CHANNEL_X=old\nB=2\n")

        changed = envfile.update(path, {"DISCORD_CHANNEL_X": "new"})

        self.assertEqual(changed, ["DISCORD_CHANNEL_X"])
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[:3], ["A=1", "DISCORD_CHANNEL_X=new", "B=2"])

    def test_comments_and_order_survive(self):
        """사람이 적어둔 메모가 날아가면 안 된다."""
        path = self._write("# 중요한 메모\nA=1\n\n# 두번째 구역\nB=2\n")

        envfile.update(path, {"A": "9"})

        text = path.read_text(encoding="utf-8")
        self.assertIn("# 중요한 메모", text)
        self.assertIn("# 두번째 구역", text)
        self.assertIn("B=2", text)

    def test_missing_key_is_appended(self):
        path = self._write("A=1\n")

        envfile.update(path, {"NEW_KEY": "42"})

        self.assertIn("NEW_KEY=42", path.read_text(encoding="utf-8"))
        self.assertIn("A=1", path.read_text(encoding="utf-8"))

    def test_unchanged_value_is_not_reported(self):
        path = self._write("A=1\n")

        self.assertEqual(envfile.update(path, {"A": "1"}), [])

    def test_no_values_leaves_file_untouched(self):
        path = self._write("A=1\n")

        self.assertEqual(envfile.update(path, {}), [])
        self.assertEqual(path.read_text(encoding="utf-8"), "A=1\n")


if __name__ == "__main__":
    unittest.main()
