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


if __name__ == "__main__":
    unittest.main()
