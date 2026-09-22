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

    def test_an_emptied_file_gets_the_schema_again(self) -> None:
        """파일을 제자리에서 비우면 inode·경로·DDL 지문이 모두 그대로다.

        캐시 키가 파일시스템 신원이면 "이미 적용했다"로 판단해 빈 DB를 그대로 쓴다.
        삭제 후 재생성은 OS가 inode를 재사용할 때만 재현되므로(Windows/NTFS에서는
        30회 중 0회) 그 경로로는 이 결함이 잡히지 않는다 — 제자리 truncate는
        어느 플랫폼에서나 같은 키를 만든다.

        진실은 파일시스템이 아니라 DB가 갖고 있어야 한다.
        """
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runtime.sqlite3"
            with runtime_sqlite.runtime_connection(path):
                pass
            identity = (path.stat().st_dev, path.stat().st_ino)
            for suffix in ("-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)
            with open(path, "wb"):
                pass
            self.assertEqual(identity, (path.stat().st_dev, path.stat().st_ino),
                             "이 테스트는 같은 inode일 때만 의미가 있다")
            with runtime_sqlite.runtime_connection(path) as connection:
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("intents", tables)

    def test_changed_declarations_are_applied_to_an_existing_file(self) -> None:
        """선언이 바뀌면 이미 있는 DB에도 다시 적용한다 — DB가 어느 선언으로 만들어졌는지 알아야 한다."""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runtime.sqlite3"
            with runtime_sqlite.runtime_connection(path):
                pass
            with mock.patch.object(runtime_sqlite, "_apply_schema", wraps=runtime_sqlite._apply_schema) as apply:
                with mock.patch.object(runtime_sqlite, "_declaration_fingerprint", return_value=12345):
                    with runtime_sqlite.runtime_connection(path):
                        pass
                    with runtime_sqlite.runtime_connection(path):
                        pass
            self.assertEqual(1, apply.call_count, "바뀐 선언은 한 번만 적용하고 그 뒤로는 건너뛴다")

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
