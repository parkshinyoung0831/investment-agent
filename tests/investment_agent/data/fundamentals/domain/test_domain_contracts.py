"""외부 I/O 없는 fundamentals 도메인 계약을 검증한다."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from investment_agent.data.fundamentals.domain.filing import (
    SUPPORTED_FORMS,
    SUPPORTED_STATEMENTS,
    normalize_form,
)
from investment_agent.data.fundamentals.domain.services.parse_earnings_release import (
    parse_earnings_release,
)


class CanonicalModuleContractTest(unittest.TestCase):
    def test_domain_does_not_import_external_adapters(self) -> None:
        domain_root = Path("src/investment_agent/data/fundamentals/domain")
        imports: set[str] = set()
        for path in domain_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
        for forbidden in (
            "investment_agent.data.fundamentals.infrastructure",
            "investment_agent.platform.db.postgres",
            "supabase",
            "yfinance",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertFalse(any(name.startswith(forbidden) for name in imports))


class FilingPolicyTest(unittest.TestCase):
    def test_amended_form_is_normalized_without_losing_supported_forms(self) -> None:
        self.assertEqual(normalize_form("10-Q/A"), "10-Q")
        self.assertIn("10-Q/A", SUPPORTED_FORMS)
        self.assertEqual(SUPPORTED_STATEMENTS, ("BS", "IS", "CF"))


class EarningsReleaseParserTest(unittest.TestCase):
    def test_extracts_revenue_and_guidance_without_network_context(self) -> None:
        revenue, guidance = parse_earnings_release("""
            <html><body>
              <p>Total revenue was $91.8 billion for the quarter.</p>
              <li>Full-year outlook guidance was raised for fiscal 2027.</li>
            </body></html>
        """)

        self.assertEqual(revenue, 91_800_000_000.0)
        self.assertEqual(
            guidance,
            "Full-year outlook guidance was raised for fiscal 2027.",
        )


if __name__ == "__main__":
    unittest.main()
