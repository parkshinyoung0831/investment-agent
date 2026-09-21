"""화면이 쓰는 로컬 원장 조회는 정렬·상한을 SQL에서 처리한다 — 원장이 커져도 전부 읽어 파이썬에서 자르지 않는다(DB-04)."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.reporting.readers import runtime


class RuntimeRowsOrderLimitTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "runtime.sqlite3"
        env = mock.patch.dict(os.environ, {"AI_INVESTOR_RUNTIME_DB_PATH": str(self.path)})
        env.start()
        self.addCleanup(env.stop)
        with runtime_connection():  # 선언된 스키마를 만든다
            pass
        with closing(sqlite3.connect(self.path)) as connection:
            for index in (2, 0, 4, 1, 3):  # 일부러 뒤섞어 넣는다
                connection.execute(
                    "INSERT INTO decision_runs(run_id, as_of_at, stage, status, candidate_tickers, started_at, finished_at) "
                    "VALUES (?, ?, 'shadow', 'completed', '[]', ?, ?)",
                    (f"run-{index}", f"2026-09-0{index + 1}T00:00:00+00:00",
                     f"2026-09-0{index + 1}T01:00:00+00:00", f"2026-09-0{index + 1}T02:00:00+00:00"),
                )
            connection.commit()

    def test_the_newest_rows_come_back_first_and_the_limit_is_applied_in_sql(self) -> None:
        rows = runtime.read_runtime_rows("decision_runs", order_by="started_at", limit=3)
        self.assertEqual(["run-4", "run-3", "run-2"], [row["run_id"] for row in rows])

    def test_without_arguments_every_row_is_returned(self) -> None:
        self.assertEqual(5, len(runtime.read_runtime_rows("decision_runs")))

    def test_order_by_must_be_a_real_column_of_the_table(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown order column"):
            runtime.read_runtime_rows("decision_runs", order_by="started_at; DROP TABLE decision_runs")

    def test_order_and_limit_are_rejected_for_datasets_that_do_not_support_them(self) -> None:
        with self.assertRaisesRegex(ValueError, "only for plain"):
            runtime.read_runtime_rows("orders", limit=5)


if __name__ == "__main__":
    unittest.main()
