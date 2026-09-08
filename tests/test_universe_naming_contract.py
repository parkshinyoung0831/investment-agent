from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UniverseNamingContractTest(unittest.TestCase):
    def test_runtime_code_has_no_retired_universe_identifiers(self):
        retired = (
            "universe.tickers",
            "ticker_predecessor_ciks",
            "sp500_memberships",
            "append_sp500_memberships",
            "current_sp500_tickers",
            "select_sp500_tickers",
            "is_is_tracked",
            "apply_ciks",
            "apply_sic_results",
            "enrich_missing_cik",
            "backfill_sic_industries",
            "fetch_sic_results",
        )
        violations: list[str] = []
        for base in (ROOT / "src", ROOT / "scripts"):
            for path in base.rglob("*.py"):
                text = path.read_text(encoding="utf-8")
                for identifier in retired:
                    if identifier in text:
                        violations.append(f"{path.relative_to(ROOT)}: {identifier}")
        self.assertEqual(violations, [])

    def test_documented_physical_columns_are_canonical(self):
        guide = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("`sic_industry_name`/`sic_division_name`", guide)
        self.assertNotIn("is_is_tracked", guide)

    def test_universe_readme_explains_v2_ownership_and_current_vs_historical_use(self):
        guide = (ROOT / "src/investment_agent/data/universe/README.md").read_text(encoding="utf-8")
        for phrase in (
            "30초 예시: Alphabet",
            "처음 만들 때만 쓰는 seed",
            "is_active_listing",
            "select_security_profiles()",
            "오늘 수집할 ticker",
            "historical backtest의 universe로 대체할 수",
            "source_not_classified",
        ):
            self.assertIn(phrase, guide)

    def test_current_schema_has_no_retired_database_names(self):
        violations: list[str] = []
        for path in (ROOT / "db" / "postgres" / "v1").rglob("*.sql"):
            relative = path.relative_to(ROOT)
            text = path.read_text(encoding="utf-8")
            for identifier in (
                "universe.tickers",
                "ticker_predecessor_ciks",
                "sp500_memberships",
            ):
                if identifier in text:
                    violations.append(f"{relative}: {identifier}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
