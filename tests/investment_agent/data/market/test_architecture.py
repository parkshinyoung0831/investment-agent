"""market 계층 경계를 검증한다. universe의 test_architecture.py(최종
수정본)와 같은 패턴 — 이름이 실제로 검사하는 것과 일치하는지, top-level
파일의 outbound 방향까지 다루는지, 제거된 경로가 재등장하지 않는지를
처음부터 포함한다."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path("src/investment_agent/data/market")


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


class MarketArchitectureTest(unittest.TestCase):
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
            "investment_agent.data.market.application",
            "investment_agent.data.market.infrastructure",
            "investment_agent.platform.db.postgres",
            "supabase",
            "requests",
            "yfinance",
        )
        for path in _python_files("domain"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(any(imported.startswith(name) for name in forbidden))

    def test_application_does_not_call_http_or_supabase_directly(self) -> None:
        """application은 infrastructure.sources와 domain만 안다.

        universe의 최종 리뷰에서 정착된 것과 같은 이유로 여기서는
        ``investment_agent.platform.db``를 forbidden에 넣지 않는다 —
        refresh_market.py는 ``db: Database``를 받아 그대로 repository
        생성자에 넘기는 합법적 패턴을 쓴다(refresh_universe.py와 동일).
        여기서 막는 것은 HTTP/공급자 라이브러리를 **직접** import하는
        경우뿐이다.
        """
        forbidden = ("requests", "yfinance")
        for path in _python_files("application"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(any(imported.startswith(name) for name in forbidden))

    def test_infrastructure_does_not_import_application_or_commands(self) -> None:
        forbidden = (
            "investment_agent.data.market.application",
            "investment_agent.data.market.commands",
        )
        for path in _python_files("infrastructure"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(any(imported.startswith(name) for name in forbidden))

    def test_top_level_files_do_not_import_application_or_commands(self) -> None:
        forbidden = (
            "investment_agent.data.market.application",
            "investment_agent.data.market.commands",
        )
        top_level = [ROOT / "repository.py", ROOT / "persistence.py"]
        for path in top_level:
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(any(imported.startswith(name) for name in forbidden))

    def test_removed_compatibility_paths_do_not_return(self) -> None:
        removed = [
            ROOT / "models.py",
            ROOT / "actions.py",
            ROOT / "adjustments.py",
            ROOT / "price_repair.py",
            ROOT / "calendar.py",
            ROOT / "retention.py",
            ROOT / "yahoo.py",
            ROOT / "archive.py",
            ROOT / "change_manifest.py",
            ROOT / "service.py",
        ]
        for path in removed:
            with self.subTest(path=path):
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
