"""fundamentals 계층 경계와 기준 진입점을 검증한다."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path("src/investment_agent/data/fundamentals")


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


class FundamentalsArchitectureTest(unittest.TestCase):
    def test_canonical_layers_exist(self) -> None:
        expected = (
            "domain",
            "domain/taxonomy",
            "domain/services",
            "application",
            "infrastructure/sec",
            "infrastructure/yahoo_finance",
            "infrastructure/supabase",
        )
        for relative in expected:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_dir())

    def test_removed_compatibility_paths_do_not_return(self) -> None:
        removed = (
            Path("src/segments"),
            Path("src/estimates"),
            ROOT / "segments",
            ROOT / "estimates",
            ROOT / "flash",
            ROOT / "clients",
            ROOT / "sources",
            ROOT / "jobs",
            # application 계층의 builders/ports/use_cases는 한 단계 평탄화되어
            # 모듈이 application/ 바로 아래에 있다. 하위 패키지가 되살아나지
            # 않는지 지킨다.
            ROOT / "application" / "builders",
            ROOT / "application" / "ports",
            ROOT / "application" / "use_cases",
            *(ROOT / name for name in (
                "columns.py",
                "concepts.py",
                "db.py",
                "etl.py",
                "provenance.py",
                "season.py",
                "standardize.py",
                "validate.py",
                "wide.py",
            )),
        )
        for path in removed:
            with self.subTest(path=path):
                self.assertFalse(path.exists())

        self.assertFalse(tuple((ROOT / "domain" / "models").glob("*.py")))
        self.assertTrue((ROOT / "domain" / "filing.py").is_file())

    def test_domain_has_no_outward_dependencies(self) -> None:
        forbidden = (
            "investment_agent.data.fundamentals.application",
            "investment_agent.data.fundamentals.infrastructure",
            "investment_agent.platform.db.postgres",
            "supabase",
            "yfinance",
        )
        for path in _python_files("domain"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(imported.startswith(forbidden))

    def test_application_depends_on_ports_and_domain_not_adapters(self) -> None:
        forbidden = (
            "investment_agent.data.fundamentals.infrastructure",
            "investment_agent.platform.db.postgres",
            "supabase",
            "yfinance",
        )
        for path in _python_files("application"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(imported.startswith(forbidden))

    def test_infrastructure_does_not_depend_on_use_cases_or_entries(self) -> None:
        # application 계층의 builders/ports/use_cases는 같은 디렉터리로 평탄화되어
        # 더는 경로 접두사로 유스케이스/빌더와 port 계약을 구분할 수 없다.
        # infrastructure가 실제로 의존해도 되는 port 계약 모듈만 허용 목록으로 둔다.
        allowed_application_modules = {
            "investment_agent.data.fundamentals.application.filing_sources",
            "investment_agent.data.fundamentals.application.market_sources",
            "investment_agent.data.fundamentals.application.repositories",
        }
        prefix = "investment_agent.data.fundamentals.application"
        for path in _python_files("infrastructure"):
            for imported in _imports(path):
                if not imported.startswith(prefix):
                    continue
                with self.subTest(path=path, imported=imported):
                    self.assertIn(imported, allowed_application_modules)

    def test_supabase_queries_stay_in_infrastructure(self) -> None:
        for layer in ("domain", "application"):
            for path in _python_files(layer):
                source = path.read_text(encoding="utf-8")
                with self.subTest(path=path):
                    self.assertNotIn('.schema("fundamentals")', source)
                    self.assertNotIn(".schema('fundamentals')", source)


if __name__ == "__main__":
    unittest.main()


_FILINGS_NAMES = {"T_FILINGS", "_FILINGS_TABLE"}
# 공시 행(`filings`)의 값을 정하는 곳은 SEC submissions를 읽는 기업 재무 공시 경로 하나다.
_FILINGS_OWNER = ROOT / "infrastructure/supabase/company_financials.py"


def _writes_filings(call: ast.Call) -> bool:
    """`...table(T_FILINGS).upsert(...)`나 `_upsert_chunked(_FILINGS_TABLE, ...)`인가."""
    func = call.func
    if isinstance(func, ast.Name) and func.id == "_upsert_chunked":
        return bool(call.args) and isinstance(call.args[0], ast.Name) and call.args[0].id in _FILINGS_NAMES
    if not (isinstance(func, ast.Attribute) and func.attr in {"upsert", "update"}):
        return False
    receiver = func.value
    return (
        isinstance(receiver, ast.Call)
        and isinstance(receiver.func, ast.Attribute)
        and receiver.func.attr == "table"
        and any(isinstance(arg, ast.Name) and arg.id in _FILINGS_NAMES for arg in receiver.args)
    )


def _ignores_duplicates(call: ast.Call) -> bool:
    return any(
        keyword.arg == "ignore_duplicates"
        and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in call.keywords
    )


def filings_overwriters(files: list[Path]) -> list[str]:
    """주인이 아닌데 기존 공시 행을 덮어쓸 수 있는 호출 위치."""
    found: list[str] = []
    for path in files:
        if path == _FILINGS_OWNER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _writes_filings(node) and not _ignores_duplicates(node):
                found.append(f"{path}:{node.lineno}")
    return found


class FilingsOwnershipTest(unittest.TestCase):
    """공시 행을 여러 곳이 다른 뜻으로 덮어쓰면 `report_date`가 조용히 바뀐다."""

    def test_only_the_filing_path_overwrites_filings(self) -> None:
        self.assertEqual([], filings_overwriters(sorted(ROOT.rglob("*.py"))))

    def test_the_guard_catches_an_overwriting_upsert(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "writer.py"
            path.write_text(
                "sb.schema(S).table(T_FILINGS).upsert(rows, on_conflict='accession_no').execute()\n",
                encoding="utf-8",
            )
            self.assertEqual([f"{path}:1"], filings_overwriters([path]))
