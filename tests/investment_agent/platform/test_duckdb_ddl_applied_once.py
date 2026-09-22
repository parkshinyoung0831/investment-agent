"""선언은 프로세스당·파일당 한 번만 적용한다(PB-2). 단, 새 파일·바뀐 선언에는 다시 적용한다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.platform.db import duckdb as duckdb_store


class DdlAppliedOnceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.ddl = root / "ddl"
        self.ddl.mkdir()
        (self.ddl / "10_a.sql").write_text("CREATE TABLE IF NOT EXISTS a (x INTEGER);", encoding="utf-8")
        self.db = root / "s.duckdb"

    def _run(self, hook=None) -> None:
        with duckdb_store.transactional_connection(self.db, ddl_dir=self.ddl, after_ddl=hook) as c:
            c.execute("INSERT INTO a VALUES (1)")

    def test_hook_runs_only_when_ddl_is_applied(self) -> None:
        calls: list[int] = []
        for _ in range(3):
            self._run(lambda _c: calls.append(1))
        self.assertEqual(len(calls), 1)

    def test_changed_declaration_is_applied_again(self) -> None:
        calls: list[int] = []
        self._run(lambda _c: calls.append(1))
        (self.ddl / "20_b.sql").write_text("CREATE TABLE IF NOT EXISTS b (y INTEGER);", encoding="utf-8")
        self._run(lambda _c: calls.append(1))
        self.assertEqual(len(calls), 2)
        with duckdb_store.connect(self.db, read_only=True) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM b").fetchone()[0], 0)

    def test_recreated_file_gets_the_declaration_again(self) -> None:
        self._run()
        self.db.unlink()
        self._run()  # 지우고 다시 만든 같은 경로 — 표가 없으면 INSERT가 실패한다
        with duckdb_store.connect(self.db, read_only=True) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM a").fetchone()[0], 1)
    def test_a_restored_artifact_missing_a_declared_column_fails_loudly(self) -> None:
        """복원한 옛 artifact에 새 컬럼이 없으면, 나중에 Binder Error로 죽지 말고 지금 말한다.

        `CREATE TABLE IF NOT EXISTS`는 표가 이미 있으면 통째로 건너뛰므로 선언에 컬럼이
        늘어나도 추가되지 않는다. 그 뒤 어딘가의 INSERT가
        `Table "feature_sets" does not have a column named "feature_set"`로 죽는데,
        그 지점에서는 원인이 "캐시에서 복원한 옛 artifact"라는 것이 보이지 않는다.
        """
        self._run()  # (x INTEGER)로 만들어진 옛 artifact
        (self.ddl / "10_a.sql").write_text(
            "CREATE TABLE IF NOT EXISTS a (x INTEGER, label VARCHAR);", encoding="utf-8")
        with self.assertRaises(duckdb_store.DuckDBStoreError) as caught:
            with duckdb_store.transactional_connection(self.db, ddl_dir=self.ddl):
                pass
        message = str(caught.exception)
        self.assertIn("label", message)
        self.assertIn("rebuild", message.lower())

    def test_a_matching_artifact_is_not_reported_as_drifted(self) -> None:
        """선언과 맞는 표를 드리프트로 신고하면 정상 실행이 멈춘다."""
        self._run()
        self._run()
        with duckdb_store.connect(self.db, read_only=True) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM a").fetchone()[0], 2)

    def test_an_invalid_file_is_not_retried_for_minutes(self) -> None:
        """잠금 재시도가 영구 오류까지 삼키면 CI가 파일 하나에 3분을 태우고 죽는다.

        잠금은 기다리면 풀리지만 "유효한 DuckDB 파일이 아님"은 기다려도 그대로다.
        """
        with open(self.db, "wb") as handle:
            handle.write(b"not a duckdb file")
        slept: list[float] = []
        with self.assertRaises(Exception):
            duckdb_store._open_with_retry(
                lambda: __import__("duckdb").connect(str(self.db)),
                target=self.db, timeout_seconds=60.0, sleep=slept.append,
            )
        self.assertEqual([], slept, "영구 오류는 한 번 시도하고 바로 올린다")


class DeclaredColumnParsingTest(unittest.TestCase):
    """드리프트 검사는 선언에서 컬럼 이름을 정확히 읽어야 한다.

    과하게 읽으면 멀쩡한 저장소를 "옛 artifact"로 신고해 파이프라인이 통째로 멈춘다 —
    실제로 컬럼 사이의 한국어 주석을 컬럼으로 읽어 테스트 42건이 죽었다.
    덜 읽으면 드리프트를 놓쳐 원래의 Binder Error로 돌아간다.
    """

    def test_comments_between_columns_are_not_columns(self) -> None:
        statement = (
            "CREATE TABLE IF NOT EXISTS content_index (\n"
            "    content_id VARCHAR PRIMARY KEY,\n"
            "    -- 소셜에는 대응하는 축이 없어 NULL이다.\n"
            "    url_hash VARCHAR UNIQUE,\n"
            "    /* PIT 축. 그때 우리가 이미 갖고 있었나 */\n"
            "    first_seen_at TIMESTAMPTZ NOT NULL\n"
            ");"
        )
        self.assertEqual(
            {"content_index": {"content_id", "url_hash", "first_seen_at"}},
            duckdb_store._declared_columns((statement,)),
        )

    def test_table_level_constraints_are_not_columns(self) -> None:
        statement = (
            "CREATE TABLE t (\n"
            "  a VARCHAR,\n"
            "  b INTEGER CHECK (b > 0),\n"
            "  PRIMARY KEY (a),\n"
            "  UNIQUE (a, b)\n"
            ");"
        )
        self.assertEqual({"t": {"a", "b"}}, duckdb_store._declared_columns((statement,)))

    def test_non_create_table_statements_declare_nothing(self) -> None:
        for statement in (
            "CREATE INDEX idx ON t (a);",
            "CREATE VIEW v AS SELECT a FROM t;",
            "DELETE FROM t WHERE a IS NULL;",
        ):
            with self.subTest(statement=statement):
                self.assertEqual({}, duckdb_store._declared_columns((statement,)))

    def test_every_declared_store_parses_without_phantom_columns(self) -> None:
        """이 저장소의 실제 선언 넷을 전부 읽어 본다.

        선언을 못 찾으면 이 검사는 공허하게 통과한다 — 표가 하나도 안 나오면 실패시킨다.
        """
        from investment_agent.platform.storage_paths import repository_root

        roots = sorted((repository_root() / "db" / "duckdb").glob("*/v1"))
        self.assertGreaterEqual(len(roots), 2, "DuckDB 선언 디렉터리를 찾지 못했다")
        for root in roots:
            with self.subTest(store=root.parent.name):
                tables = duckdb_store._declared_columns(duckdb_store.ddl_statements(root))
                self.assertTrue(tables, f"{root}에서 표를 하나도 읽지 못했다")
                for table, columns in tables.items():
                    for column in columns:
                        self.assertRegex(
                            column, r"^[a-z_][a-z0-9_]*$",
                            f"{table}의 '{column}'은 컬럼 이름이 아니다 — 주석이나 제약을 읽었다",
                        )


if __name__ == "__main__":
    unittest.main()
