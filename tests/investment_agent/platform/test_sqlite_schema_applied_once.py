"""runtime 원장 스키마는 파일당 한 번만 적용한다 — 연결마다 선언 전체를 다시 실행하지 않는다(PF-1)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from investment_agent.platform.db import sqlite as runtime_sqlite


class SchemaAppliedOnceTest(unittest.TestCase):
    def test_repeated_connections_apply_the_schema_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runtime.sqlite3"
            with mock.patch.object(runtime_sqlite, "_apply_schema", wraps=runtime_sqlite._apply_schema) as apply:
                for _ in range(4):
                    with runtime_sqlite.runtime_connection(path):
                        pass
            self.assertEqual(apply.call_count, 1)

    def test_a_recreated_file_gets_the_schema_again(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runtime.sqlite3"
            with mock.patch.object(runtime_sqlite, "_apply_schema", wraps=runtime_sqlite._apply_schema) as apply:
                with runtime_sqlite.runtime_connection(path):
                    pass
                for suffix in ("", "-wal", "-shm"):
                    Path(str(path) + suffix).unlink(missing_ok=True)
                with runtime_sqlite.runtime_connection(path) as connection:
                    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(apply.call_count, 2)
            self.assertIn("intents", tables)

    def test_a_refused_migration_is_not_remembered(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runtime.sqlite3"
            with mock.patch.object(runtime_sqlite, "_apply_schema", side_effect=runtime_sqlite.RuntimeMigrationRequired("x")) as apply:
                for _ in range(2):
                    with self.assertRaises(runtime_sqlite.RuntimeMigrationRequired):
                        with runtime_sqlite.runtime_connection(path):
                            pass
            self.assertEqual(apply.call_count, 2)


if __name__ == "__main__":
    unittest.main()
