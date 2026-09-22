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



class StoreAvailabilityGateTest(unittest.TestCase):
    """빈 목록을 반환하는 loader는 `available` 확인 뒤에만 불러야 한다.

    `load_news`·`load_social`·`load_trending`은 저장소를 못 열면 빈 목록을 돌려준다
    (`reporting/readers/intelligence.py`). 그것만 보면 "보관된 것이 없다"와
    "저장소 장애"가 같아 보인다. 저장소 상태를 말하는 것은 `load_overview()["available"]`
    하나뿐이므로, 그 게이트 **안에서만** 나머지를 부르는 구조를 고정한다.
    """

    GUARDED = ("load_news", "load_social", "load_trending")

    def _availability_gate(self, tree: ast.Module) -> ast.If:
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and "available" in ast.unparse(node.test):
                return node
        self.fail("available 게이트를 찾지 못했다 — 이 검사가 공허하게 통과하는 중이다")

    def test_the_guarded_loaders_are_actually_called(self) -> None:
        """호출을 못 찾으면 아래 검사가 공허하게 통과한다."""
        source = PAGE.read_text(encoding="utf-8")
        for name in self.GUARDED:
            self.assertIn(name, source)

    def test_every_empty_list_loader_sits_inside_the_availability_gate(self) -> None:
        tree = ast.parse(PAGE.read_text(encoding="utf-8"))
        gate = self._availability_gate(tree)
        # 이름이 아니라 **호출 자리**로 센다. 이름으로 빼면 게이트 안에 같은 이름의
        # 호출이 하나만 있어도 게이트 밖의 호출이 지워져 가드가 공허하게 통과한다.
        inside = {
            id(node)
            for branch in (gate.body, gate.orelse)
            for statement in branch
            for node in ast.walk(statement)
        }
        outside = sorted(
            f"{node.func.attr} (line {node.lineno})"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in self.GUARDED and id(node) not in inside
        )
        self.assertEqual([], outside, "available 게이트 밖에서 부르는 loader")
        called_inside = {
            node.func.attr
            for branch in (gate.body, gate.orelse)
            for statement in branch
            for node in ast.walk(statement)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        for name in self.GUARDED:
            self.assertIn(name, called_inside, f"{name}이 게이트 안에 없다")


if __name__ == "__main__":
    unittest.main()
