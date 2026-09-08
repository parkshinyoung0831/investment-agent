"""macro 도메인 계층의 의존 방향을 검증한다."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path("src/investment_agent/data/macro")
DOMAIN_FORBIDDEN = (
    "requests",
    "yfinance",
    "fredapi",
    "bs4",
    "pandas_datareader",
    "investment_agent.data.macro.repository",
    "investment_agent.data.macro.releases.db",
    "investment_agent.data.macro.releases.commands",
    "investment_agent.data.macro.releases.sources",
    "investment_agent.data.macro.application",
    "investment_agent.data.macro.infrastructure",
    "investment_agent.data.macro.commands",
    "investment_agent.operations",
)
REMOVED_RULE_MODULES = (
    ROOT / "catalog.py",
    ROOT / "quality.py",
    ROOT / "revisions.py",
    ROOT / "releases" / "baseline.py",
    ROOT / "releases" / "identity.py",
    ROOT / "releases" / "normalize.py",
    ROOT / "releases" / "release_catalog.py",
    ROOT / "releases" / "schedule.py",
    ROOT / "releases" / "validation.py",
)
DOMAIN_RULE_MODULES = (
    ROOT / "domain" / "catalog.py",
    ROOT / "domain" / "quality.py",
    ROOT / "domain" / "revisions.py",
    ROOT / "domain" / "releases" / "baseline.py",
    ROOT / "domain" / "releases" / "identity.py",
    ROOT / "domain" / "releases" / "normalize.py",
    ROOT / "domain" / "releases" / "release_catalog.py",
    ROOT / "domain" / "releases" / "schedule.py",
    ROOT / "domain" / "releases" / "validation.py",
)
APPLICATION_SERVICE_MODULES = (
    ROOT / "application" / "refresh_market_state.py",
    ROOT / "application" / "release_calendar.py",
)
REMOVED_ORCHESTRATION_MODULES = (
    ROOT / "service.py",
    ROOT / "releases" / "etl.py",
)
COMMAND_MODULES = (
    ROOT / "commands" / "__init__.py",
    ROOT / "commands" / "macro_refresh.py",
    ROOT / "commands" / "econ_calendar_daily.py",
    ROOT / "commands" / "econ_calendar_backfill.py",
    ROOT / "commands" / "econ_calendar_publish_ics.py",
    ROOT / "commands" / "econ_calendar_revision_audit.py",
    ROOT / "commands" / "econ_calendar_validate.py",
)
REMOVED_COMMAND_MODULES = (
    Path("src/investment_agent/operations/commands/macro_refresh.py"),
    Path("src/investment_agent/data/macro/releases/commands/__init__.py"),
    Path("src/investment_agent/data/macro/releases/commands/econ_calendar_daily.py"),
    Path("src/investment_agent/data/macro/releases/commands/econ_calendar_backfill.py"),
    Path("src/investment_agent/data/macro/releases/commands/econ_calendar_publish_ics.py"),
    Path("src/investment_agent/data/macro/releases/commands/econ_calendar_revision_audit.py"),
    Path("src/investment_agent/data/macro/releases/commands/econ_calendar_validate.py"),
)
COMMAND_ALLOWED_MACRO_IMPORTS = (
    "investment_agent.data.macro.domain",
    "investment_agent.data.macro.application",
    "investment_agent.data.macro.infrastructure",
    "investment_agent.data.macro.repository",
    "investment_agent.data.macro.releases",
)
COMMAND_FORBIDDEN_IMPORTS = (
    "investment_agent.data.macro.releases.commands",
    "investment_agent.operations.commands.macro_refresh",
)
APPLICATION_PROVIDER_IMPORTS = (
    "requests",
    "yfinance",
    "fredapi",
    "bs4",
    "pandas_datareader",
)
APPLICATION_RAW_DATABASE_OPERATIONS = (
    "table",
    "upsert",
    "rpc",
    "select_paged",
)
INFRASTRUCTURE_PACKAGE_MARKERS = (
    ROOT / "infrastructure" / "__init__.py",
    ROOT / "infrastructure" / "sources" / "__init__.py",
    ROOT / "infrastructure" / "releases" / "__init__.py",
    ROOT / "infrastructure" / "releases" / "sources" / "__init__.py",
)
INFRASTRUCTURE_SOURCE_MODULES = (
    ROOT / "infrastructure" / "fetch.py",
    ROOT / "infrastructure" / "settings.py",
    ROOT / "infrastructure" / "sources" / "ecos.py",
    ROOT / "infrastructure" / "sources" / "fred.py",
    ROOT / "infrastructure" / "sources" / "market.py",
    ROOT / "infrastructure" / "sources" / "web.py",
    ROOT / "infrastructure" / "sources" / "yfinance.py",
    ROOT / "infrastructure" / "releases" / "ics.py",
    ROOT / "infrastructure" / "releases" / "sources" / "actuals.py",
    ROOT / "infrastructure" / "releases" / "sources" / "alfred.py",
    ROOT / "infrastructure" / "releases" / "sources" / "fomc_calendar.py",
    ROOT / "infrastructure" / "releases" / "sources" / "fred_calendar.py",
    ROOT / "infrastructure" / "releases" / "sources" / "gdpnow_archive.py",
    ROOT / "infrastructure" / "releases" / "sources" / "nowcast.py",
)
REMOVED_INFRASTRUCTURE_PATHS = (
    ROOT / "collection.py",
    ROOT / "settings.py",
    ROOT / "collectors" / "__init__.py",
    ROOT / "collectors" / "ecos.py",
    ROOT / "collectors" / "fred.py",
    ROOT / "collectors" / "market.py",
    ROOT / "collectors" / "web.py",
    ROOT / "collectors" / "yfinance.py",
    ROOT / "releases" / "ics.py",
    ROOT / "releases" / "sources" / "__init__.py",
    ROOT / "releases" / "sources" / "actuals.py",
    ROOT / "releases" / "sources" / "alfred.py",
    ROOT / "releases" / "sources" / "fomc_calendar.py",
    ROOT / "releases" / "sources" / "fred_calendar.py",
    ROOT / "releases" / "sources" / "gdpnow_archive.py",
    ROOT / "releases" / "sources" / "nowcast.py",
)
INFRASTRUCTURE_FORBIDDEN = (
    "investment_agent.data.macro.application",
    "investment_agent.data.macro.commands",
    "investment_agent.operations",
)


def _importing_package(path: Path) -> tuple[str, ...]:
    relative = path.relative_to(ROOT).with_suffix("")
    package = ("investment_agent", "data", "macro", *relative.parts)
    return package[:-1]


def _import_from_modules(node: ast.ImportFrom, package: tuple[str, ...]) -> set[str]:
    if node.level == 0:
        return {node.module} if node.module else set()
    base = package[:len(package) - node.level + 1]
    if node.module:
        return {".".join((*base, node.module))}
    return {
        ".".join((*base, alias.name))
        for alias in node.names
        if alias.name != "*"
    }


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    package = _importing_package(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(_import_from_modules(node, package))
    return names


def _python_files(directory: str) -> list[Path]:
    return sorted((ROOT / directory).rglob("*.py"))


def _domain_code_files() -> list[Path]:
    """Domain 아래의 모든 Python 모듈을 검사한다."""
    return _python_files("domain")


def _application_code_files() -> list[Path]:
    """Application 아래의 모든 Python 모듈을 검사한다."""
    return _python_files("application")


def _infrastructure_code_files() -> list[Path]:
    """Infrastructure 아래의 모든 Python 모듈을 검사한다."""
    return _python_files("infrastructure")


def _command_code_files() -> list[Path]:
    """Commands 아래의 모든 Python 모듈을 검사한다."""
    return _python_files("commands")


def _raw_database_operations(path: Path) -> set[str]:
    """호출 간 공백과 무관하게 raw Database 메서드 호출을 찾는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in APPLICATION_RAW_DATABASE_OPERATIONS
    }


class MacroArchitectureTest(unittest.TestCase):
    def test_package_initializer_resolves_relative_repository_import(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory) / "macro"
            initializer = temporary_root / "domain" / "__init__.py"
            initializer.parent.mkdir(parents=True)
            initializer.write_text("from .. import repository\n", encoding="utf-8")

            with patch(f"{__name__}.ROOT", temporary_root):
                imports = _imports(initializer)

        expected = "investment_agent.data.macro.repository"
        self.assertIn(expected, imports)
        self.assertTrue(expected.startswith(DOMAIN_FORBIDDEN))

    def test_imports_resolve_absolute_and_relative_macro_modules(self) -> None:
        path = ROOT / "domain" / "rules.py"
        fixtures = (
            (
                "from investment_agent.data.macro.repository import MacroRepository\n",
                "investment_agent.data.macro.repository",
            ),
            (
                "from .. import repository\n",
                "investment_agent.data.macro.repository",
            ),
            (
                "from ..repository import MacroRepository\n",
                "investment_agent.data.macro.repository",
            ),
        )
        for source, expected in fixtures:
            with self.subTest(source=source), patch.object(
                Path,
                "read_text",
                return_value=source,
            ):
                self.assertIn(expected, _imports(path))

    def test_domain_file_enumeration_includes_every_domain_module(self) -> None:
        expected = [
            ROOT / "domain" / "__init__.py",
            ROOT / "domain" / "rules.py",
            ROOT / "domain" / "releases" / "identity.py",
        ]

        def files_for(directory: str) -> list[Path]:
            return expected if directory == "domain" else []

        with patch(f"{__name__}._python_files", side_effect=files_for):
            self.assertEqual(expected, _domain_code_files())

    def test_pure_rule_modules_live_in_domain_packages(self) -> None:
        self.assertTrue((ROOT / "domain").is_dir())
        self.assertTrue((ROOT / "domain" / "releases").is_dir())
        for path in DOMAIN_RULE_MODULES:
            with self.subTest(path=path):
                self.assertTrue(path.is_file())

    def test_legacy_pure_rule_modules_are_removed(self) -> None:
        for path in REMOVED_RULE_MODULES:
            with self.subTest(path=path):
                self.assertFalse(path.exists())

    def test_application_modules_exist(self) -> None:
        self.assertTrue((ROOT / "application").is_dir())
        for path in APPLICATION_SERVICE_MODULES:
            with self.subTest(path=path):
                self.assertTrue(path.is_file())

    def test_infrastructure_source_packages_and_modules_exist(self) -> None:
        for path in (*INFRASTRUCTURE_PACKAGE_MARKERS, *INFRASTRUCTURE_SOURCE_MODULES):
            with self.subTest(path=path):
                self.assertTrue(path.is_file())

    def test_legacy_source_adapter_paths_are_removed(self) -> None:
        for path in REMOVED_INFRASTRUCTURE_PATHS:
            with self.subTest(path=path):
                self.assertFalse(path.exists())

    def test_raw_database_operation_parser_catches_whitespace(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "service.py"
            path.write_text('db.table ("macro", "series")\n', encoding="utf-8")

            self.assertEqual({"table"}, _raw_database_operations(path))

    def test_legacy_orchestration_modules_are_removed(self) -> None:
        for path in REMOVED_ORCHESTRATION_MODULES:
            with self.subTest(path=path):
                self.assertFalse(path.exists())

    def test_command_package_and_modules_exist(self) -> None:
        self.assertTrue((ROOT / "commands").is_dir())
        for path in COMMAND_MODULES:
            with self.subTest(path=path):
                self.assertTrue(path.is_file())

    def test_legacy_command_modules_are_removed(self) -> None:
        for path in REMOVED_COMMAND_MODULES:
            with self.subTest(path=path):
                self.assertFalse(path.exists())

    def test_command_code_uses_canonical_macro_dependencies(self) -> None:
        for path in _command_code_files():
            for imported in _imports(path):
                if not imported.startswith("investment_agent.data.macro"):
                    continue
                with self.subTest(path=path, imported=imported):
                    self.assertTrue(
                        imported.startswith(COMMAND_ALLOWED_MACRO_IMPORTS),
                        msg=f"path={path}, imported={imported}",
                    )
                    self.assertFalse(
                        imported.startswith(COMMAND_FORBIDDEN_IMPORTS),
                        msg=f"path={path}, imported={imported}",
                    )

    def test_application_code_has_no_provider_imports_or_raw_database_operations(self) -> None:
        for path in _application_code_files():
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(imported.startswith(APPLICATION_PROVIDER_IMPORTS))
            operations = _raw_database_operations(path)
            for operation in APPLICATION_RAW_DATABASE_OPERATIONS:
                with self.subTest(path=path, operation=operation):
                    self.assertNotIn(operation, operations)

    def test_infrastructure_code_does_not_depend_on_application_or_commands(self) -> None:
        for path in _infrastructure_code_files():
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(
                        imported.startswith(INFRASTRUCTURE_FORBIDDEN),
                        msg=f"path={path}, imported={imported}",
                    )

    def test_domain_forbidden_dependencies_include_legacy_adapters(self) -> None:
        self.assertIn(
            "investment_agent.data.macro.releases.commands",
            DOMAIN_FORBIDDEN,
        )
        self.assertIn(
            "investment_agent.data.macro.releases.sources",
            DOMAIN_FORBIDDEN,
        )

    def test_domain_code_has_no_outward_dependencies(self) -> None:
        for path in _domain_code_files():
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(
                        imported.startswith(DOMAIN_FORBIDDEN),
                        msg=f"path={path}, imported={imported}",
                    )

    def test_repository_contracts_do_not_import_application_or_commands(self) -> None:
        forbidden = (
            "investment_agent.data.macro.application",
            "investment_agent.data.macro.commands",
        )
        for path in (ROOT / "repository.py", ROOT / "releases" / "db.py"):
            for imported in _imports(path):
                with self.subTest(path=path, imported=imported):
                    self.assertFalse(
                        imported.startswith(forbidden),
                        msg=f"path={path}, imported={imported}",
                    )


if __name__ == "__main__":
    unittest.main()
