"""universe 계층 경계를 검증한다. fundamentals의 test_architecture.py와 같은 패턴."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path("src/investment_agent/data/universe")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _python_files(directory: str) -> list[Path]:
    return sorted((ROOT / directory).rglob("*.py"))


class UniverseArchitectureTest(unittest.TestCase):
    def test_canonical_layers_exist(self) -> None:
        expected = (
            "domain",
            "infrastructure/sources",
            "application",
            "commands",
        )
        for relative in expected:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_dir())

    def test_domain_has_no_outward_dependencies(self) -> None:
        forbidden = (
            "investment_agent.data.universe.application",
            "investment_agent.data.universe.infrastructure",
            "investment_agent.platform.db.postgres",
            "supabase",
            "requests",
        )
        for path in _python_files("domain"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(imported.startswith(forbidden))

    def test_application_does_not_call_http_libraries_directly(
        self,
    ) -> None:
        """application은 infrastructure.sources와 domain만 안다.

        repository.py/persistence.py/watchlists.db는 이번 파일럿에서 옮기지
        않았으므로(외부 공개 계약) 여기서는 강제하지 않는다 — collection.py는
        여전히 ``investment_agent.data.universe.persistence`` (모듈 별칭
        ``db``)를 부른다. 이 테스트는 대신 application이 SEC·Nasdaq·
        Wikipedia·Toss HTTP 라이브러리를 **직접** import하지 않는지만 본다.
        """
        forbidden = ("requests", "pandas")
        for path in _python_files("application"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(any(imported.startswith(name) for name in forbidden))

    def test_infrastructure_sources_do_not_import_application_or_commands(
        self,
    ) -> None:
        forbidden = (
            "investment_agent.data.universe.application",
            "investment_agent.data.universe.commands",
        )
        for path in _python_files("infrastructure/sources"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(imported.startswith(forbidden))

    def test_top_level_files_do_not_import_application_or_commands(self) -> None:
        """repository.py/persistence.py/watchlists/*는 application·commands가

        소비하는 쪽이다 — 거꾸로 이들을 import하면 import 순환이 생긴다.
        예를 들어 application의 collection.py가 언젠가 persistence.py에
        다시 import되면, 이 테스트가 없으면 아무도 잡지 못한다.
        """
        forbidden = (
            "investment_agent.data.universe.application",
            "investment_agent.data.universe.commands",
        )
        paths = [ROOT / "repository.py", ROOT / "persistence.py", *sorted((ROOT / "watchlists").rglob("*.py"))]
        for path in paths:
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(imported.startswith(forbidden))

    def test_removed_compatibility_paths_do_not_return(self) -> None:
        """이 계층화 작업에서 지운 옛 평면 구조 파일이 재도입 shim으로

        다시 생기지 않았는지 본다. stale import를 "고친다"며 한 줄짜리
        re-export shim을 다시 만들면 옛 평면 구조가 조용히 되살아난다.
        """
        removed = (
            ROOT / "models.py",
            ROOT / "identifiers.py",
            ROOT / "normalization.py",
            ROOT / "sec.py",
            ROOT / "sec_entities.py",
            ROOT / "nasdaq_trader.py",
            ROOT / "sp500.py",
            ROOT / "toss.py",
            ROOT / "service.py",
            ROOT / "collection.py",
        )
        for path in removed:
            with self.subTest(path=path):
                self.assertFalse(path.exists())
        self.assertFalse((ROOT / "watchlists" / "sources").exists())


if __name__ == "__main__":
    unittest.main()
