"""intelligence 계층 경계를 검증한다.

data 도메인들과 같은 4계층 문법을 쓴다 — 저장소만 Supabase가 아니라 로컬
DuckDB·Parquet이다. 뉴스와 소셜을 한 패키지로 묶었으므로 둘이 도메인 규칙을
공유하는지도 여기서 지킨다.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path("src/investment_agent/intelligence")


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


class IntelligenceArchitectureTest(unittest.TestCase):
    def test_canonical_layers_exist(self) -> None:
        for relative in ("domain", "infrastructure/sources", "application", "commands"):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_dir())

    def test_domain_has_no_outward_dependencies(self) -> None:
        """도메인 규칙이 저장소나 네트워크를 알면 규칙만 따로 시험할 수 없다."""
        forbidden = (
            "investment_agent.intelligence.application",
            "investment_agent.intelligence.infrastructure",
            "investment_agent.intelligence.persistence",
            "investment_agent.intelligence.repository",
            "investment_agent.platform.db",
            "supabase",
            "requests",
        )
        for path in _python_files("domain"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(any(imported.startswith(name) for name in forbidden))

    def test_application_does_not_call_http_directly(self) -> None:
        """application은 infrastructure.sources와 domain만 안다.

        universe·market과 같은 이유로 `platform.db`는 막지 않는다 — 진입점이 만든
        `Database`를 받아 저장소 생성자에 넘기는 합법적 패턴이 있다. 여기서 막는 것은
        HTTP/공급자 라이브러리를 **직접** import하는 경우뿐이다.
        """
        forbidden = ("requests", "praw", "yfinance", "httpx")
        for path in _python_files("application"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(any(imported.split(".")[0] == name for name in forbidden))

    def test_infrastructure_does_not_import_application_or_commands(self) -> None:
        forbidden = (
            "investment_agent.intelligence.application",
            "investment_agent.intelligence.commands",
        )
        for path in _python_files("infrastructure"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(any(imported.startswith(name) for name in forbidden))

    def test_top_level_files_do_not_import_application_or_commands(self) -> None:
        forbidden = (
            "investment_agent.intelligence.application",
            "investment_agent.intelligence.commands",
        )
        for path in (ROOT / "repository.py",):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(any(imported.startswith(name) for name in forbidden))

    def test_news_and_social_share_one_package(self) -> None:
        """따로 두면 정규화·언급 추출 규칙이 두 벌이 되고 조용히 갈라진다."""
        for gone in ("data/news", "data/social", "data/intelligence"):
            with self.subTest(path=gone):
                self.assertFalse(Path("src/investment_agent") .joinpath(gone).exists())
        self.assertTrue((ROOT / "domain" / "news_normalize.py").is_file())
        self.assertTrue((ROOT / "domain" / "social_normalize.py").is_file())

    def test_removed_flat_paths_do_not_return(self) -> None:
        """평면 모듈이 하나라도 돌아오면 도메인마다 문법이 달라진다."""
        removed = (
            "models.py", "contracts.py", "normalize.py", "extract.py", "catalog.py",
            "service.py", "provider.py", "retention.py", "db.py", "sources",
        )
        for name in removed:
            with self.subTest(name=name):
                self.assertFalse((ROOT / name).exists())


if __name__ == "__main__":
    unittest.main()
