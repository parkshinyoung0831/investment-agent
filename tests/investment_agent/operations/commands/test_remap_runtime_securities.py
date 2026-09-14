"""옛 종목 ID를 가진 로컬 판단 원장이 전부 풀릴 때만, 백업 뒤 한 번에 옮겨지는지."""
from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from investment_agent.operations.commands.remap_runtime_securities import apply_remap, plan_remap


def _ledger(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE security_decisions (case_key TEXT, security_id INTEGER)")
    connection.execute("CREATE TABLE signals (case_key TEXT, security_id INTEGER)")
    connection.executemany("INSERT INTO security_decisions VALUES (?, ?)",
                           [("AAPL__20260909__20d__v1", 2), ("MSFT__20260909__20d__v1", 1000001)])
    connection.execute("INSERT INTO signals VALUES (?, ?)", ("AAPL__20260909__20d__v1", 2))
    connection.commit()
    connection.close()


class RemapTest(unittest.TestCase):
    def test_only_stale_ids_move_and_a_backup_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "runtime.sqlite3"
            _ledger(database)
            with closing(sqlite3.connect(database)) as connection:
                plan = plan_remap(connection, resolve=lambda tickers: {"AAPL": 1000002},
                                  known_ids=lambda ids: {1000001})
            self.assertEqual(len(plan["changes"]), 2)
            backup = apply_remap(database, plan)
            self.assertTrue(backup.exists())
            with closing(sqlite3.connect(database)) as connection:
                rows = dict(connection.execute("SELECT case_key, security_id FROM security_decisions"))
                signal = connection.execute("SELECT security_id FROM signals").fetchone()[0]
            self.assertEqual(rows["AAPL__20260909__20d__v1"], 1000002)
            self.assertEqual(rows["MSFT__20260909__20d__v1"], 1000001)
            self.assertEqual(signal, 1000002)
            with closing(sqlite3.connect(backup)) as connection:
                self.assertEqual(connection.execute("SELECT security_id FROM signals").fetchone()[0], 2)

    def test_any_unresolvable_row_blocks_the_whole_remap(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "runtime.sqlite3"
            _ledger(database)
            with closing(sqlite3.connect(database)) as connection:
                plan = plan_remap(connection, resolve=lambda tickers: {}, known_ids=lambda ids: {1000001})
            with self.assertRaises(RuntimeError):
                apply_remap(database, plan)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT security_id FROM signals").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
