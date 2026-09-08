"""Data owner 내부의 불필요한 한 단계 래퍼가 돌아오지 않게 한다."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path("src/investment_agent/data")


class DataPackageLayoutTest(unittest.TestCase):
    def test_shallow_internal_wrappers_are_flattened(self) -> None:
        removed = (
            ROOT / "fundamentals/domain/models",
            ROOT / "macro/application/services",
            ROOT / "macro/domain/market_state",
            ROOT / "market/application/services",
            ROOT / "universe/application/services",
        )
        for path in removed:
            with self.subTest(path=path):
                self.assertFalse(tuple(path.glob("*.py")))

    def test_flattened_modules_have_canonical_paths(self) -> None:
        expected = (
            ROOT / "fundamentals/domain/filing.py",
            ROOT / "macro/application/refresh_market_state.py",
            ROOT / "macro/application/release_calendar.py",
            ROOT / "macro/domain/catalog.py",
            ROOT / "macro/domain/quality.py",
            ROOT / "macro/domain/revisions.py",
            ROOT / "market/application/refresh_market.py",
            ROOT / "universe/application/collection.py",
            ROOT / "universe/application/refresh_universe.py",
        )
        for path in expected:
            with self.subTest(path=path):
                self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
