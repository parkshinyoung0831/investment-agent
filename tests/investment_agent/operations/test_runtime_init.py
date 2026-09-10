"""Actions 러너가 읽기 전에 로컬 runtime 원장을 명시적으로 준비한다."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from investment_agent.operations.commands import runtime_init


class RuntimeInitTest(unittest.TestCase):
    def test_creates_notification_schema_at_the_requested_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "nested" / "runtime.sqlite3"

            result = runtime_init.main(["--path", str(database)])

            self.assertEqual(0, result)
            self.assertTrue(database.is_file())
            with closing(sqlite3.connect(
                f"{database.resolve().as_uri()}?mode=ro", uri=True
            )) as connection:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertIn("notification_outbox", tables)
            self.assertIn("notification_deliveries", tables)


if __name__ == "__main__":
    unittest.main()
