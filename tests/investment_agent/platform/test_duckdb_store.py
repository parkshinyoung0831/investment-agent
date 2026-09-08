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


if __name__ == "__main__":
    unittest.main()
