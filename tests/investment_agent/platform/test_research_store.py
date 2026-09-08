"""읽기 전용 Research 조회와 재실행의 발송 상태 보존을 확인한다."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_agent.platform.db import duckdb as duckdb_store
from investment_agent.research.storage.repository import RESEARCH_DDL_DIR, ResearchStore


class ResearchStoreTest(unittest.TestCase):
    def test_research_schema_is_declared_in_sql_files(self):
        statements = duckdb_store.ddl_statements(RESEARCH_DDL_DIR)
        joined = "\n".join(statements)
        self.assertEqual(
            [
                "00_init.sql",
                "10_datasets.sql",
                "20_experiments.sql",
                "30_models.sql",
                "40_backtests.sql",
                "90_views.sql",
            ],
            [path.name for path in sorted(RESEARCH_DDL_DIR.glob("*.sql"))],
        )
        for table in (
            "feature_sets",
            "dataset_runs",
            "strategy_runs",
            "strategy_allocations",
            "datasets",
            "experiments",
            "models",
            "backtests",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", joined)

    def test_read_only_missing_snapshot_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing/research.duckdb"
            with self.assertRaises(FileNotFoundError):
                ResearchStore(path, read_only=True).allocations()
            self.assertFalse(path.parent.exists())

    def test_read_only_connection_rejects_writes_and_reads_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.duckdb"
            ResearchStore(path).upsert_allocation(self.allocation())
            store = ResearchStore(path, read_only=True)
            self.assertEqual("GEM", store.allocations()[0]["strategy_id"])
            import duckdb
            with self.assertRaises(duckdb.InvalidInputException):
                store.upsert_allocation(self.allocation())

    def test_recompute_does_not_store_notification_status(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.duckdb")
            row = self.allocation()
            store.upsert_allocation({**row, "discord_sent_at": "2026-09-01T00:00:00Z"})
            store.upsert_allocation(row)
            # Discord 발송 여부는 runtime outbox가 소유한다. Research 결과는 발송
            # 상태와 무관하게 같은 관계형 allocation으로 재구성된다.
            self.assertEqual("GEM", store.allocations(pending_only=True)[0]["strategy_id"])

    def test_weights_are_rows_not_a_json_column(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.duckdb")
            store.upsert_allocation(self.allocation())
            with store._connect() as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(strategy_allocations)").fetchall()}
                weights = connection.execute("SELECT asset_symbol, weight FROM strategy_allocations").fetchall()
            self.assertEqual({"run_id", "asset_symbol", "weight"}, columns)
            self.assertEqual([("SPY", 1.0)], weights)

    def test_legacy_json_allocations_are_migrated_after_ddl_is_loaded(self):
        import duckdb

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.duckdb"
            with duckdb.connect(str(path)) as connection:
                connection.execute(
                    """
                    CREATE TABLE strategy_allocations (
                        strategy_id VARCHAR PRIMARY KEY,
                        decision_date DATE NOT NULL,
                        apply_date DATE NOT NULL,
                        mode VARCHAR NOT NULL,
                        weights JSON NOT NULL,
                        signals JSON NOT NULL
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO strategy_allocations VALUES (?, ?, ?, ?, ?, ?)",
                    ["GEM", "2026-08-31", "2026-09-01", "risk_on", '{"SPY":1.0}', "{}"],
                )

            rows = ResearchStore(path).allocations()

            self.assertEqual("GEM", rows[0]["strategy_id"])
            self.assertEqual({"SPY": 1.0}, rows[0]["weights"])
            with duckdb.connect(str(path), read_only=True) as connection:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(strategy_allocations)"
                    ).fetchall()
                }
            self.assertEqual({"run_id", "asset_symbol", "weight"}, columns)

    @staticmethod
    def allocation():
        return {"strategy_id": "GEM", "decision_date": "2026-08-31", "apply_date": "2026-09-01",
                "mode": "risk_on", "weights": {"SPY": 1.0}, "signals": {}}
