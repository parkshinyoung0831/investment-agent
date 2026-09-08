from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts.migrate_local_storage import (
    LocalStorageConflict,
    copy_duckdb_snapshot,
    copy_sqlite_snapshot,
    main,
    plan_migrations,
)


EMPTY_PATH_ENV = {
    "AI_INVESTOR_LOCAL_DATA_ROOT": "",
    "AI_INVESTOR_LOCAL_ARTIFACT_ROOT": "",
    "AI_INVESTOR_INTELLIGENCE_DB_PATH": "",
    "INVESTMENT_AGENT_RESEARCH_ROOT": "",
    "AI_INVESTOR_RUNTIME_DB_PATH": "",
}


class LocalStorageMigrationTest(unittest.TestCase):
    def test_plan_is_read_only_and_lists_each_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", EMPTY_PATH_ENV
        ):
            root = Path(directory)
            plans = plan_migrations(root)

            self.assertEqual(
                ["intelligence", "research", "runtime"],
                [plan.store for plan in plans],
            )
            self.assertTrue(all(plan.action == "missing_source" for plan in plans))
            self.assertEqual([], list(root.rglob("*")))

    def test_both_legacy_and_target_refuse_automatic_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", EMPTY_PATH_ENV
        ):
            root = Path(directory)
            legacy = root / "data/local/runtime.sqlite3"
            target = root / "data/local/runtime/runtime.sqlite3"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy")
            target.parent.mkdir(parents=True)
            target.write_bytes(b"target")

            with self.assertRaises(LocalStorageConflict):
                plan_migrations(root)

    def test_sqlite_snapshot_keeps_source_and_verifies_logical_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "legacy.sqlite3"
            target = root / "runtime/runtime.sqlite3"
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("CREATE TABLE ledger(id INTEGER PRIMARY KEY, value TEXT)")
                connection.executemany(
                    "INSERT INTO ledger(value) VALUES (?)", [("one",), ("two",)]
                )
                connection.commit()

            result = copy_sqlite_snapshot(source, target)

            self.assertTrue(source.is_file())
            self.assertTrue(target.is_file())
            self.assertEqual(2, result.source_rows)
            self.assertEqual(result.source_rows, result.target_rows)
            self.assertEqual(result.source_sha256, result.target_sha256)
            with closing(sqlite3.connect(target)) as connection:
                self.assertEqual(
                    [(1, "one"), (2, "two")],
                    connection.execute("SELECT * FROM ledger ORDER BY id").fetchall(),
                )

    def test_duckdb_snapshot_keeps_source_and_verifies_schema_and_rows(self) -> None:
        import duckdb

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "legacy.duckdb"
            target = root / "research/research.duckdb"
            with duckdb.connect(str(source)) as connection:
                connection.execute("CREATE TABLE observations(id INTEGER, value VARCHAR)")
                connection.execute("INSERT INTO observations VALUES (1, 'one'), (2, 'two')")

            result = copy_duckdb_snapshot(source, target)

            self.assertTrue(source.is_file())
            self.assertTrue(target.is_file())
            self.assertEqual({"main.observations": 2}, result.table_rows)
            self.assertEqual(result.source_rows, result.target_rows)
            self.assertEqual(result.source_sha256, result.target_sha256)

    def test_copy_refuses_to_replace_an_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "legacy.sqlite3"
            target = root / "runtime.sqlite3"
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("CREATE TABLE ledger(id INTEGER)")
                connection.commit()
            target.write_bytes(b"existing")

            with self.assertRaises(LocalStorageConflict):
                copy_sqlite_snapshot(source, target)
            self.assertEqual(b"existing", target.read_bytes())

    def test_apply_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(SystemExit):
            main(["apply"])


if __name__ == "__main__":
    unittest.main()
