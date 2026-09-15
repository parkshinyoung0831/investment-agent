"""로컬 DuckDB 파일을 여는 공통 경계의 계약."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.platform.db import duckdb as duckdb_store

DDL_DIR = Path("db/duckdb/intelligence/v1")


class DuckDBStoreTest(unittest.TestCase):
    def test_ddl_statements_follow_file_name_order(self) -> None:
        statements = duckdb_store.ddl_statements(DDL_DIR)
        joined = "\n".join(statements)
        self.assertIn("content_files", joined)
        self.assertLess(joined.index("content_files"), joined.index("entity_mentions"))

    def test_connect_applies_declared_schema(self) -> None:
        """intelligence 본문은 이제 Parquet가 소유하고 DuckDB는 작은 catalog/index
        metadata만 갖는다 — news_articles/social_posts/collection_runs 본문 표는 없다.

        색인도 종류별로 나누지 않는다. `content_index` 하나가 `content_kind`로
        가르므로, 중복 제거·보존·신선도를 두 번 쓰지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "intelligence.duckdb"
            with duckdb_store.connect(path, ddl_dir=DDL_DIR) as connection:
                names = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT table_name FROM information_schema.tables"
                    ).fetchall()
                }
            self.assertLessEqual(
                {"content_files", "content_catalog_state", "content_index",
                 "entity_mentions"},
                names,
            )
            self.assertNotIn("news_article_index", names)
            self.assertNotIn("social_post_index", names)

    def test_read_only_refuses_a_missing_file(self) -> None:
        """읽기 전용 연결이 파일을 만들면, 화면이 빈 DB를 만들어 놓고
        수집 잡의 쓰기 잠금을 빼앗는다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "absent.duckdb"
            with self.assertRaises(duckdb_store.DuckDBStoreError):
                duckdb_store.connect(path, read_only=True)
            self.assertFalse(path.exists())

    def test_missing_ddl_directory_is_refused(self) -> None:
        with self.assertRaises(duckdb_store.DuckDBStoreError):
            duckdb_store.ddl_statements(Path("db/duckdb/does_not_exist/v1"))



class DuckDBOpenRetryTest(unittest.TestCase):
    """다른 프로세스가 파일을 잡고 있으면 즉시 죽지 않고 제한 시간 동안 기다린다."""

    def test_busy_file_is_retried_until_it_opens(self):
        import duckdb
        from investment_agent.platform.db import duckdb as store

        calls, sleeps = [], []

        def open_file():
            calls.append(1)
            if len(calls) < 3:
                raise duckdb.IOException("file is being used by another process")
            return "connection"

        clock = iter(range(100))
        result = store._open_with_retry(open_file, target=Path("x.duckdb"), timeout_seconds=10,
                                        sleep=sleeps.append, monotonic=lambda: next(clock))
        self.assertEqual(result, "connection")
        self.assertEqual(len(calls), 3)

    def test_lock_that_outlives_the_timeout_is_raised(self):
        import duckdb
        from investment_agent.platform.db import duckdb as store

        def open_file():
            raise duckdb.IOException("busy")

        clock = iter(range(100))
        with self.assertRaises(duckdb.IOException):
            store._open_with_retry(open_file, target=Path("x.duckdb"), timeout_seconds=3,
                                   sleep=lambda seconds: None, monotonic=lambda: next(clock))

    def test_non_lock_errors_are_not_retried(self):
        from investment_agent.platform.db import duckdb as store

        calls = []

        def open_file():
            calls.append(1)
            raise ValueError("bad path")

        with self.assertRaises(ValueError):
            store._open_with_retry(open_file, target=Path("x.duckdb"), timeout_seconds=10, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)

    def test_real_second_process_waits_for_the_writer_to_release(self):
        import subprocess
        import sys
        import time as clock
        from investment_agent.platform.db.duckdb import connect

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "busy.duckdb"
            connect(target).close()
            holder = subprocess.Popen([sys.executable, "-c", (
                "import duckdb,time,sys;c=duckdb.connect(sys.argv[1]);print('held',flush=True);time.sleep(3);c.close()"
            ), str(target)], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(), "held")
                started = clock.monotonic()
                connection = connect(target)
                connection.close()
                self.assertGreater(clock.monotonic() - started, 0.5)
            finally:
                holder.wait(timeout=30)
                holder.stdout.close()


if __name__ == "__main__":
    unittest.main()
