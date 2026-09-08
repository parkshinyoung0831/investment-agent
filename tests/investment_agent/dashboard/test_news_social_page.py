"""News/Social 화면의 경계. 화면은 reporting 계약만 읽는다."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

PAGE = Path("src/investment_agent/dashboard/app_pages/news_social.py")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules.add(node.module)
    return modules


class NewsSocialPageTest(unittest.TestCase):
    def test_page_exists(self) -> None:
        self.assertTrue(PAGE.is_file())

    def test_page_reads_only_reporting(self) -> None:
        offenders = sorted(
            module
            for module in _imports(PAGE)
            if module.startswith("investment_agent.")
            and not module.startswith(
                ("investment_agent.reporting", "investment_agent.dashboard", "investment_agent.platform")
            )
        )
        self.assertEqual([], offenders)

    def test_page_does_not_touch_duckdb_or_the_legacy_db_module(self) -> None:
        """이 페이지는 새 경로가 실제로 성립하는지 보이는 증거다."""
        modules = _imports(PAGE)
        self.assertNotIn("duckdb", modules)
        self.assertNotIn("investment_agent.dashboard.db", modules)

    def test_page_is_registered_in_the_app(self) -> None:
        app = Path("src/investment_agent/dashboard/app.py").read_text(encoding="utf-8")
        self.assertIn("news_social", app)


if __name__ == "__main__":
    unittest.main()
