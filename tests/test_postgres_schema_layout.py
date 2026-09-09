"""PostgreSQL v1 SQL의 역할별 설치 순서를 고정한다."""
from __future__ import annotations

import unittest
from pathlib import Path

from scripts import db_bootstrap, postgres_schema_layout, v1_reset, v1_schema_probe


class PostgresSchemaLayoutTest(unittest.TestCase):
    def test_declares_structure_and_views_as_distinct_phases(self) -> None:
        self.assertEqual(
            (
                "00_extensions.sql",
                "10_universe.sql",
                "20_market.sql",
                "30_fundamentals.sql",
                "40_macro.sql",
                "50_institutional.sql",
            ),
            postgres_schema_layout.STRUCTURE_SQL_FILES,
        )
        self.assertEqual(("90_reporting.sql",), postgres_schema_layout.VIEW_SQL_FILES)

    def test_installation_needs_no_post_collection_seed_phase(self) -> None:
        """선언이 수집된 행에 의존하면 빈 DB를 한 번에 세울 수 없다."""
        self.assertFalse(hasattr(postgres_schema_layout, "DEPENDENT_SEED_SQL_FILES"))
        self.assertFalse(hasattr(postgres_schema_layout, "dependent_seed_files"))
        self.assertEqual(
            [], sorted(postgres_schema_layout.POSTGRES_V1_DIR.glob("*_seed.sql"))
        )

    def test_full_installation_orders_views_after_every_structure_file(self) -> None:
        files = postgres_schema_layout.installation_files()

        self.assertEqual(
            (*postgres_schema_layout.STRUCTURE_SQL_FILES, *postgres_schema_layout.VIEW_SQL_FILES),
            tuple(path.name for path in files),
        )

    def test_every_postgres_installer_uses_the_single_layout_manifest(self) -> None:
        expected = (*postgres_schema_layout.STRUCTURE_SQL_FILES, *postgres_schema_layout.VIEW_SQL_FILES)

        self.assertEqual(expected, db_bootstrap.INSTALLATION_SQL_FILES)
        self.assertEqual(expected, v1_reset.STRUCTURE_SQL_FILES)
        self.assertEqual(expected, v1_schema_probe.STRUCTURE_SQL_FILES)

    def test_active_operational_documents_do_not_reference_removed_schema_files(self) -> None:
        removed = (
            "60_trading.sql",
            "70_execution.sql",
            "80_notifications.sql",
            "85_operations.sql",
            "12_universe_watchlist_seed.sql",
            "11_universe_seed.sql",
        )
        for path in (
            Path("docs/OPERATIONS.md"),
            Path("docs/STORAGE_MAP.md"),
            Path("docs/AUTONOMOUS_SYSTEM.md"),
            Path("src/investment_agent/data/macro/releases/README.md"),
        ):
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                self.assertFalse(any(name in source for name in removed), path)


if __name__ == "__main__":
    unittest.main()
