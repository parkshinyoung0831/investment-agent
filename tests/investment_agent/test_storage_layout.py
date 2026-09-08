from __future__ import annotations

import unittest
from pathlib import Path

from scripts import db_bootstrap


ROOT = Path(__file__).resolve().parents[2]


class StorageLayoutTest(unittest.TestCase):
    def test_postgres_v1_is_the_only_canonical_root(self) -> None:
        self.assertTrue((ROOT / "db/postgres/v1/10_universe.sql").is_file())
        self.assertFalse((ROOT / "db/v1").exists())

    def test_bootstrap_uses_postgres_v1(self) -> None:
        self.assertEqual(
            ROOT / "db/postgres/v1",
            db_bootstrap.POSTGRES_V1_DIR,
        )


if __name__ == "__main__":
    unittest.main()
