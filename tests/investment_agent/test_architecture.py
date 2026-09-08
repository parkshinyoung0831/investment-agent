"""v1 패키지의 경계를 코드로 못박는다.

경계는 문서에 적어두면 지켜지지 않는다. 그래서 사람이 아니라 테스트가 지킨다.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "investment_agent"

# platform이 기대도 되는 것. config는 값을 받아오는 통로라 예외다.
PLATFORM_ALLOWED_INTERNAL = {"investment_agent.config", "investment_agent.platform"}

# platform 구성. 새 파일을 늘리려면 이 목록과 그 이유를 함께 고친다.
# 저장 기술은 `db/` 아래에 한 파일씩 둔다 — `platform.db` 하나로는 세 저장소 중
# 무엇을 여는지 이름이 말하지 않는다. research 산출물 저장소는 표 이름을 알기
# 때문에 platform이 아니라 `research/storage/`가 소유한다.
PLATFORM_MODULES = {
    "artifacts",
    "cache",
    "clock",
    "external_usage",
    "logging",
    "retry",
    "serialization",
    "storage_paths",
}
PLATFORM_DB_MODULES = {"postgres", "duckdb", "sqlite"}

# platform에 있으면 안 되는 도메인 의존성. 이것이 들어오는 순간 platform은
# "기술 공통"이 아니라 "아무거나 넣는 곳"이 된다.
DOMAIN_LIBRARIES = {"yfinance", "sec_edgar", "playwright", "pandas_market_calendars", "discord"}


def _modules(package: Path) -> list[Path]:
    return sorted(p for p in package.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


class PlatformBoundaryTest(unittest.TestCase):
    def test_platform_holds_only_the_declared_modules(self) -> None:
        found = {
            p.stem for p in _modules(PACKAGE / "platform")
            if p.stem != "__init__" and p.parent.name == "platform"
        }
        self.assertEqual(PLATFORM_MODULES, found)

    def test_each_storage_technology_has_its_own_file(self) -> None:
        """한 파일이 두 저장소를 알면 부르는 쪽이 무엇을 여는지 이름으로 못 고른다."""
        found = {
            p.stem for p in _modules(PACKAGE / "platform" / "db")
            if p.stem != "__init__"
        }
        self.assertEqual(PLATFORM_DB_MODULES, found)

    def test_the_db_package_does_not_re_export_a_default_store(self) -> None:
        """`platform.db`만 적어도 통과하면 Supabase 자리에서 SQLite를 열 수 있다."""
        path = PACKAGE / "platform" / "db" / "__init__.py"
        for name in _imported_names(path):
            self.assertFalse(
                name.startswith("investment_agent."),
                f"{path.name}이 저장소 모듈을 재수출한다: {name}",
            )

    def test_platform_does_not_import_domain_packages(self) -> None:
        offenders: list[str] = []
        for path in _modules(PACKAGE / "platform"):
            for name in _imported_names(path):
                if not name.startswith("investment_agent."):
                    continue
                if not any(name == ok or name.startswith(ok + ".") for ok in PLATFORM_ALLOWED_INTERNAL):
                    offenders.append(f"{path.relative_to(ROOT)} -> {name}")
        self.assertEqual([], sorted(offenders))

    def test_platform_does_not_import_domain_libraries(self) -> None:
        offenders: list[str] = []
        for path in _modules(PACKAGE / "platform"):
            for name in _imported_names(path):
                if name.split(".")[0] in DOMAIN_LIBRARIES:
                    offenders.append(f"{path.relative_to(ROOT)} -> {name}")
        self.assertEqual([], sorted(offenders))


class DataBoundaryTest(unittest.TestCase):
    """data 파이프라인끼리 서로를 부르지 않는다.

    직접 부르면 한쪽의 실패가 다른 쪽 실행을 막고, 그 의존은 코드를 훑어야만 보인다.
    연결은 저장소를 통해서만 한다 — universe가 tracked 게이트인 것도 표를 통해서다.
    """

    # universe는 identity 게이트라 예외다. DB에서도 모든 스키마가 `universe.securities`와
    # `universe.entities`를 FK로 참조한다 — 선언된 FK와 같은 방향의 import는 숨은 결합이
    # 아니라 그 관계를 코드로 적은 것이다. 막고 싶은 것은 그것이 아니라 **파이프라인이
    # 서로의 수집 로직을 부르는 것**이다.
    #
    # intelligence도 같은 이유로 예외다 — news·social 각자의 수집 로직을 부르는 게
    # 아니라, 둘이 공유하는 `IntelligenceRepository` 저장 경계를 부른다.
    IDENTITY_GATE = "universe"
    STORAGE_GATES = frozenset({"universe", "intelligence"})

    def test_pipelines_do_not_import_each_other(self) -> None:
        data = PACKAGE / "data"
        if not data.exists():
            self.skipTest("data package is not built yet")
        offenders: list[str] = []
        for path in _modules(data):
            owner = path.relative_to(data).parts[0]
            for name in _imported_names(path):
                if not name.startswith("investment_agent.data."):
                    continue
                other = name.split(".")[2]
                if other == owner or other in self.STORAGE_GATES:
                    continue
                offenders.append(f"{path.relative_to(ROOT)} -> {name}")
        self.assertEqual([], sorted(offenders))


class StrategyMarketBoundaryTest(unittest.TestCase):
    """전략은 provider adapter가 아니라 market의 저장 계약을 소비한다."""

    def test_strategies_do_not_import_yahoo_client(self) -> None:
        root = PACKAGE / "research" / "strategies"
        offenders = [
            str(path.relative_to(ROOT))
            for path in _modules(root)
            if any(name == "yfinance" or name.startswith("yfinance.") for name in _imported_names(path))
        ]
        self.assertEqual([], offenders)


class DashboardReportingBoundaryTest(unittest.TestCase):
    """Reporting으로 옮긴 화면이 dashboard DB god module로 돌아가지 않는다."""

    _MIGRATED = {
        "app_pages/macro.py",
        "app_pages/econ_calendar.py",
        "app_pages/gurus.py",
        "app_pages/ml_rl_lab.py",
    }
    IDENTITY_GATE = "universe"

    def test_migrated_pages_do_not_import_dashboard_db(self) -> None:
        offenders = []
        root = PACKAGE / "dashboard"
        for relative in self._MIGRATED:
            path = root / relative
            if "investment_agent.dashboard.db" in path.read_text(encoding="utf-8"):
                offenders.append(relative)
        self.assertEqual([], sorted(offenders))

    def test_price_reader_is_not_imported_from_dashboard_db(self) -> None:
        pages = (PACKAGE / "dashboard" / "app_pages").glob("*.py")
        offenders = [path.name for path in pages if "dashboard.db import load_price_history" in path.read_text(encoding="utf-8")]
        self.assertEqual([], sorted(offenders))

    def test_the_identity_gate_depends_on_no_other_pipeline(self) -> None:
        """예외는 한 방향뿐이다. 게이트가 남을 부르면 순환이 생긴다.

        `DataBoundaryTest.STORAGE_GATES`의 각 게이트를 검사한다 — `universe`만
        보면 `intelligence`가 news/social을 부르지 않는 한 방향 예외는 무엇도
        지켜주지 않는다. news.service가 이미 intelligence.repository를 부르므로,
        반대 방향(intelligence → news/social)이 생기면 그것은 진짜 순환이다.
        """
        for gate in sorted(DataBoundaryTest.STORAGE_GATES):
            package = PACKAGE / "data" / gate
            if not package.exists():
                continue
            offenders = [
                f"{path.relative_to(ROOT)} -> {name}"
                for path in _modules(package)
                for name in _imported_names(path)
                if name.startswith("investment_agent.data.")
                and name.split(".")[2] != gate
            ]
            with self.subTest(gate=gate):
                self.assertEqual([], sorted(offenders))

    def test_data_does_not_import_downstream_layers(self) -> None:
        """수집이 판단·알림·화면을 알면 방향이 뒤집힌다."""
        data = PACKAGE / "data"
        if not data.exists():
            self.skipTest("data package is not built yet")
        downstream = ("research", "trading", "execution", "reporting", "notifications", "dashboard")
        offenders: list[str] = []
        for path in _modules(data):
            for name in _imported_names(path):
                for layer in downstream:
                    if name.startswith(f"investment_agent.{layer}"):
                        # Toss OAuth is a shared credential client used by the
                        # universe enrichment source; it is not trading execution.
                        if name == "investment_agent.execution.brokers.toss.auth":
                            continue
                        offenders.append(f"{path.relative_to(ROOT)} -> {name}")
        self.assertEqual([], sorted(offenders))


class LayerDirectionTest(unittest.TestCase):
    """계층 사이 화살표는 한 방향이다.

    되돌리기 어려운 쪽(execution)이 되돌리기 쉬운 쪽을 알면, 안전 경계를 고칠 때마다
    무관한 코드가 함께 흔들린다. execution은 승인된 계약만 받아 주문 경계를 수행한다.
    """

    FORBIDDEN = {
        # execution은 판단이 어떻게 만들어졌는지 알 필요가 없다. 승인된 계획만 받는다.
        "execution": ("trading", "research", "data", "notifications", "dashboard"),
        # review §32의 dependency map에 따라 trading은 stable execution contract를 소비한다.
        # 주문 mutation은 여전히 execution 내부에서만 일어난다.
        "trading": ("notifications", "dashboard"),
    }

    def test_layers_do_not_import_downstream(self) -> None:
        offenders: list[str] = []
        for layer, forbidden in self.FORBIDDEN.items():
            root = PACKAGE / layer
            if not root.exists():
                continue
            for path in _modules(root):
                for name in _imported_names(path):
                    for other in forbidden:
                        if name.startswith(f"investment_agent.{other}"):
                            offenders.append(f"{path.relative_to(ROOT)} -> {name}")
        self.assertEqual([], sorted(offenders))

    def test_the_rule_covers_layers_that_exist(self) -> None:
        """검사 대상이 하나도 없으면 위 검사는 아무것도 지키지 않는다."""
        present = [layer for layer in self.FORBIDDEN if (PACKAGE / layer).exists()]
        self.assertTrue(present, "검사 대상 계층이 아직 없다")


class LiveFlagTest(unittest.TestCase):
    """실거래 스위치는 **사람이 켠다.** 코드가 쓰는 자리가 있으면 안 된다.

    `.env`나 CI에서 사람이 넣는 것과, 코드가 실행 중에 바꾸는 것은 전혀 다른 일이다.
    후자가 가능하면 "지금 실거래인가"라는 질문에 코드를 다 읽어야만 답할 수 있다.
    """

    GUARDED = ("TOSS_LIVE_ENABLED", "LIVE_ENABLED", "TRADING_KILL_SWITCH")

    def test_no_module_assigns_a_live_flag(self) -> None:
        offenders: list[str] = []
        for path in _modules(PACKAGE):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                # os.environ["FLAG"] = ... / os.environ.setdefault("FLAG", ...)
                targets: list[ast.AST] = []
                if isinstance(node, ast.Assign):
                    targets = list(node.targets)
                elif isinstance(node, ast.AugAssign):
                    targets = [node.target]
                for target in targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value in self.GUARDED
                    ):
                        offenders.append(f"{path.relative_to(ROOT)}: assigns {target.slice.value}")
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"setdefault", "putenv", "pop", "update"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value in self.GUARDED
                ):
                    offenders.append(f"{path.relative_to(ROOT)}: mutates {node.args[0].value}")
        self.assertEqual([], sorted(offenders))

    def test_the_flags_are_actually_referenced_somewhere(self) -> None:
        """이름이 바뀌었는데 목록만 남으면 위 검사가 공허하게 통과한다."""
        seen = "\n".join(
            path.read_text(encoding="utf-8") for path in _modules(PACKAGE)
        )
        for flag in ("TOSS_LIVE_ENABLED", "TRADING_KILL_SWITCH"):
            with self.subTest(flag=flag):
                self.assertIn(flag, seen)


class PackageImportTest(unittest.TestCase):
    def test_package_inits_have_no_import_time_side_effects(self) -> None:
        """import만으로 `.env`를 읽거나 클라이언트를 만들면 테스트가 환경에 물든다."""
        offenders: list[str] = []
        for path in PACKAGE.rglob("__init__.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in tree.body:
                # 선언(docstring, __future__, 상수)만 허용한다. 호출은 부작용이다.
                if isinstance(node, (ast.Expr, ast.ImportFrom, ast.Import, ast.Assign, ast.AnnAssign)):
                    if isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant):
                        offenders.append(f"{path.relative_to(ROOT)}: {ast.dump(node)[:60]}")
                    continue
                offenders.append(f"{path.relative_to(ROOT)}: {type(node).__name__}")
        self.assertEqual([], sorted(offenders))


if __name__ == "__main__":
    unittest.main()
