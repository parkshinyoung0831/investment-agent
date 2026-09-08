"""CLAUDE.md 핵심 관례를 기계로 강제한다.

문서에만 적힌 규칙은 지켜지는지 아무도 모르는 채로 드리프트한다. 여기 있는 것은
사람의 판단 없이 판정할 수 있는 규칙뿐이고, 판단이 필요한 규칙(주석의 결, 이름이
역할을 말하는지)은 여전히 리뷰의 몫이다.

예외를 허용할 때는 목록에 경로를 적고 왜 예외인지 함께 적는다 — 예외가 늘기만 하고
이유가 없으면 규칙이 아니라 장식이 된다.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

SRC = Path("src")
NOTIFY = SRC / "investment_agent" / "notifications"

LEGACY_RUNTIME_PATHS = (
    Path("src/common"),
    Path("src/discord_admin"),
    Path("src/ops/__init__.py"),
    Path("src/ops/harness"),
    Path("src/ops/harness_adapters.py"),
    Path("src/notify"),
    Path("src/pipelines"),
    Path("src/trading"),
    Path("src/evaluation"),
    Path("src/ai_investor"),
    Path("src/contracts.py"),
    Path("src/investment_agent/entries"),
    Path("src/investment_agent/trading/execution"),
    Path("src/investment_agent/dashboard/external.py"),
    Path("src/investment_agent/dashboard/cache.py"),
    Path("src/investment_agent/notifications/text.py"),
    Path("src/investment_agent/dashboard/models.py"),
)

LEGACY_TEST_PATHS = (
    Path("tests/ai_investor"),
    Path("tests/execution"),
    Path("tests/investment_agent/test_equivalence_notifications.py"),
    Path("tests/investment_agent/test_equivalence_reporting.py"),
)


class RepositoryLayoutTest(unittest.TestCase):
    """v1의 실제 소유 경로와 폐기 경로를 파일 시스템에서 고정한다."""

    def test_legacy_runtime_paths_are_absent(self) -> None:
        present = [path.as_posix() for path in LEGACY_RUNTIME_PATHS if path.exists()]
        self.assertEqual([], present, "폐기한 런타임 경로가 남아 있다")

    def test_legacy_ops_directory_has_no_python_sources(self) -> None:
        legacy_root = SRC.parent / "ops"
        source_files = sorted(
            path.as_posix()
            for path in legacy_root.rglob("*.py")
            if "__pycache__" not in path.parts
        ) if legacy_root.is_dir() else []
        self.assertEqual([], source_files, "폐기한 src/ops에 Python 소스가 남아 있다")

    def test_legacy_test_packages_are_absent(self) -> None:
        present = [path.as_posix() for path in LEGACY_TEST_PATHS if path.exists()]
        self.assertEqual([], present, "폐기한 테스트 패키지가 남아 있다")

    def test_canonical_domain_roots_are_real_packages(self) -> None:
        roots = (
            SRC / "investment_agent" / "platform",
            SRC / "investment_agent" / "data",
            SRC / "investment_agent" / "research",
            SRC / "investment_agent" / "trading",
            SRC / "investment_agent" / "notifications",
            SRC / "investment_agent" / "execution",
        )
        missing = [path.as_posix() for path in roots if not (path / "__init__.py").is_file()]
        self.assertEqual([], missing, "canonical owner가 Python package가 아니다")

    def test_every_canonical_python_owner_directory_is_a_package(self) -> None:
        canonical = SRC / "investment_agent"
        package_dirs = sorted(
            {path.parent for path in canonical.rglob("*.py") if "__pycache__" not in path.parts}
        )
        missing = [path.as_posix() for path in package_dirs if not (path / "__init__.py").is_file()]
        self.assertEqual([], missing, "Python 파일을 소유한 canonical 디렉터리에 __init__.py가 없다")

    def test_every_test_owner_directory_is_a_package(self) -> None:
        test_root = Path("tests")
        package_dirs = sorted(
            {path.parent for path in test_root.rglob("*.py") if "__pycache__" not in path.parts}
        )
        missing = [path.as_posix() for path in package_dirs if not (path / "__init__.py").is_file()]
        self.assertEqual([], missing, "Python 파일을 소유한 테스트 디렉터리에 __init__.py가 없다")

    def test_canonical_trees_have_no_empty_directories(self) -> None:
        empty: list[str] = []
        for base in (SRC / "investment_agent", Path("tests") / "investment_agent"):
            for directory in base.rglob("*"):
                if not directory.is_dir() or directory.name == "__pycache__":
                    continue
                children = [item for item in directory.iterdir() if item.name != "__pycache__"]
                # 모듈 이동 뒤 남은 bytecode cache는 source tree의 디렉터리가 아니다.
                # clean checkout에는 생기지 않으며, 로컬 검증이 import 순서에 물들지
                # 않도록 cache만 남은 경로는 빈 canonical owner로 세지 않는다.
                if not children and (directory / "__pycache__").is_dir():
                    continue
                if not children:
                    empty.append(directory.as_posix())
        self.assertEqual([], sorted(empty), "canonical tree에 빈 디렉터리가 남아 있다")


class OpenSourceDocumentationTest(unittest.TestCase):
    """공개 저장소의 최소 문서 표면과 개인 환경정보 차단을 고정한다."""

    REQUIRED_PUBLIC_DOCS = (
        Path("CONTRIBUTING.md"),
        Path("CODE_OF_CONDUCT.md"),
        Path("SECURITY.md"),
        Path("docs/OPEN_SOURCE_READINESS.md"),
    )

    def test_public_policy_documents_exist(self) -> None:
        missing = [path.as_posix() for path in self.REQUIRED_PUBLIC_DOCS if not path.is_file()]
        self.assertEqual([], missing, "공개 저장소 정책 문서가 누락됐다")

    def test_root_readme_links_public_policy_documents(self) -> None:
        source = Path("README.md").read_text(encoding="utf-8")
        missing = [
            path.as_posix()
            for path in self.REQUIRED_PUBLIC_DOCS
            if path.as_posix() not in source
        ]
        self.assertEqual([], missing, "README가 공개 정책 문서를 연결하지 않는다")

    def test_public_docs_do_not_contain_machine_specific_absolute_paths(self) -> None:
        offenders: list[str] = []
        for path in [Path("README.md"), *Path("docs").rglob("*.md")]:
            source = path.read_text(encoding="utf-8")
            if re.search(r"(?:[A-Za-z]:\\Users\\|/Users/|/home/)", source):
                offenders.append(path.as_posix())
        self.assertEqual([], offenders, "공개 문서에 개인 장비 절대 경로가 있다")

    def test_environment_reference_is_not_a_private_handoff_copy(self) -> None:
        source = Path("docs/ENV.md").read_text(encoding="utf-8")
        self.assertNotIn("CLAUDE.md에서 옮겨 온", source)
        self.assertNotIn("실측 2026-", source)

    def test_env_example_has_no_credentials_or_private_endpoints(self) -> None:
        sensitive_names = re.compile(
            r"^(?:SUPABASE_(?:URL|SERVICE_KEY|DB_URL)|EDGAR_USER_AGENT|"
            r"(?:FRED|ECOS|EIA|OPENFIGI|ALPHA_VANTAGE|FINNHUB)_API_KEY|"
            r"(?:TOSS|KIS|DISCORD|AI_INVESTOR|OPS_HEARTBEAT).*?(?:KEY|SECRET|TOKEN|"
            r"WEBHOOK|URL|ACCOUNT_NO))$"
        )
        offenders: list[str] = []
        for line_number, line in enumerate(Path(".env.example").read_text(encoding="utf-8").splitlines(), 1):
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if sensitive_names.match(name) and value.strip():
                offenders.append(f".env.example:{line_number}:{name}")
        self.assertEqual([], offenders, "공개 환경변수 예제에 credential 또는 private endpoint가 있다")


def _modules(root: Path = SRC) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _posix(path: Path) -> str:
    return path.as_posix()


def _imported_modules(path: Path) -> set[str]:
    """모듈이 가져오는 절대 모듈 경로. 상대 import는 파일 위치로 풀어서 돌려준다.

    상대 import를 그대로 두면 `from ..ai_investor import x`가 문자열 비교를 빠져나가
    계층 검사에 구멍이 난다.
    """
    package = list(path.parent.parts)
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                modules.add(".".join(base + ([node.module] if node.module else [])))
            elif node.module:
                modules.add(node.module)
    return modules


def _has_main_guard(tree: ast.Module) -> bool:
    """`if __name__ == "__main__":` 블록이 있으면 CLI로 직접 실행되는 모듈이다."""
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
        ):
            return True
    return False


class FutureAnnotationsTest(unittest.TestCase):
    """관례 4 — 모든 모듈의 첫 import는 `from __future__ import annotations`."""

    def test_every_module_postpones_annotation_evaluation(self) -> None:
        missing = []
        for path in _modules():
            tree = _tree(path)
            body = tree.body
            # docstring만 있는 네임스페이스 __init__.py 는 미룰 annotation이 없다.
            code = [n for n in body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            if path.name == "__init__.py" and not code:
                continue
            found = any(
                isinstance(n, ast.ImportFrom) and n.module == "__future__"
                and any(a.name == "annotations" for a in n.names)
                for n in body
            )
            if not found:
                missing.append(_posix(path))
        self.assertEqual([], missing, "from __future__ import annotations 누락")


class PublicExportTest(unittest.TestCase):
    """명시한 공개 표면에 동일한 이름을 두 번 노출하지 않는다."""

    def test_static_all_exports_are_unique(self) -> None:
        offenders: list[str] = []
        for path in _modules():
            tree = _tree(path)
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
                    continue
                if not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                    continue
                try:
                    values = ast.literal_eval(node.value)
                except (ValueError, TypeError, SyntaxError):
                    continue
                if isinstance(values, (list, tuple, set)) and len(values) != len(set(values)):
                    offenders.append(f"{_posix(path)}:{node.lineno}")
        self.assertEqual([], offenders, "__all__에 중복 공개 이름이 있다")


class DatabaseNameConstantsTest(unittest.TestCase):
    """관례 17 — 스키마·테이블·RPC 이름은 모듈 상수로만 부른다.

    문자열을 직접 쓰면 오타가 import 에러가 아니라 런타임 PGRST 404로만 드러나고,
    테스트는 네트워크를 때리지 않으므로 못 잡는다.
    """

    def test_no_literal_schema_table_or_rpc_names(self) -> None:
        literals = []
        for path in _modules():
            for node in ast.walk(_tree(path)):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if node.func.attr not in {"table", "rpc", "schema"} or not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    literals.append(f"{_posix(path)}:{node.lineno} .{node.func.attr}({first.value!r})")
        self.assertEqual([], literals, "DB 이름 리터럴 — 모듈 상수를 쓰세요")


class RetiredWriterTest(unittest.TestCase):
    """호출처 없는 과거 연구 writer를 trading facade에 되살리지 않는다."""

    def test_trading_facade_has_no_retired_research_writers(self) -> None:
        path = SRC / "investment_agent" / "trading" / "supabase_repository.py"
        source = path.read_text(encoding="utf-8")
        for method in (
            "attach_run_account_snapshot",
            "save_market_regime",
            "save_candidate_ranks",
            "save_attribution_report",
            "save_portfolio_evaluation",
            "market_price_history",
            "latest_strategy_allocations",
        ):
            with self.subTest(method=method):
                self.assertNotRegex(source, rf"\bdef {method}\b")


class JsonLoggingTest(unittest.TestCase):
    """관례 3 — 라이브러리 코드는 `print()` 대신 JSON 로거를 쓴다.

    사람이 눈으로 읽으라고 있는 CLI 출력만 예외다. 그 판정은 위치로 한다 —
    `entries/` 아래이거나, 스스로 `__main__` 가드를 갖고 직접 실행되는 모듈.
    """

    # GUI 제어센터. entries/ 밖이고 __main__ 가드도 없지만 run.bat이 직접 띄우는
    # 셸이라 기동 실패를 stdout JSON으로 알려야 한다.
    PRINT_ALLOWED = {"src/investment_agent/operations/control_center.py"}

    def test_print_is_confined_to_command_line_entry_points(self) -> None:
        offenders = []
        for path in _modules():
            posix = _posix(path)
            if "entries" in path.parts or posix in self.PRINT_ALLOWED:
                continue
            tree = _tree(path)
            if _has_main_guard(tree):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                    offenders.append(f"{posix}:{node.lineno}")
        self.assertEqual([], offenders, "print() 대신 get_logger(__name__)을 쓰세요")

    def test_loggers_are_named_after_their_module(self) -> None:
        """로거 이름은 항상 `__name__` — 고정 문자열은 어느 모듈이 냈는지 지운다."""
        offenders = []
        for path in _modules():
            for node in ast.walk(_tree(path)):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                    continue
                if node.func.id != "get_logger" or not node.args:
                    continue
                first = node.args[0]
                if not (isinstance(first, ast.Name) and first.id == "__name__"):
                    offenders.append(f"{_posix(path)}:{node.lineno}")
        self.assertEqual([], offenders, "get_logger()에는 __name__ 만 넘기세요")


class NotifyPackageShapeTest(unittest.TestCase):
    """관례 16 — 알림 producer는 v1 notifications 아래에 있다."""

    def _packages(self) -> list[Path]:
        return sorted(
            d for d in NOTIFY.iterdir()
            if d.is_dir() and not d.name.startswith("_") and d.name not in {"channels", "renderers", "discord_admin"}
        )

    def test_every_package_exposes_run_and_owns_its_queries(self) -> None:
        for package in self._packages():
            with self.subTest(package=package.name):
                runners = sorted(package.glob("run*.py"))
                if package.name == "macro":
                    runners = sorted(package.glob("core.py")) + sorted(package.glob("watch.py"))
                self.assertTrue(runners, f"{package.name}: run.py 또는 run_*.py 가 없다")
                for runner in runners:
                    # 정의든 재노출이든 `<모듈>:run` 으로 잡히기만 하면 계약을 지킨 것이다.
                    tree = _tree(runner)
                    bound = {
                        n.name for n in tree.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    }
                    for node in tree.body:
                        if isinstance(node, (ast.Import, ast.ImportFrom)):
                            bound |= {a.asname or a.name.split(".")[0] for a in node.names}
                    self.assertIn("run", bound, f"{_posix(runner)}: run 이 잡히지 않는다")

    def test_packages_never_import_each_other(self) -> None:
        """producer끼리는 직접 import하지 않고 shared notification 계층을 쓴다."""
        offenders = []
        for path in _modules(NOTIFY):
            relative = path.relative_to(NOTIFY)
            if len(relative.parts) < 2:
                continue
            owner = relative.parts[0]
            if owner in {"channels", "renderers"}:
                continue
            for node in ast.walk(_tree(path)):
                modules = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules.append(node.module)
                elif isinstance(node, ast.Import):
                    modules.extend(a.name for a in node.names)
                for module in modules:
                    if not module.startswith("investment_agent.notifications."):
                        continue
                    target = module.split(".")[2]
                    if target not in {
                        owner, "channels", "renderers", "outbox", "service", "subscriptions",
                        "playwright", "quickchart", "text",
                    }:
                        offenders.append(f"{_posix(path)} -> {module}")
        self.assertEqual([], offenders, "알림 패키지끼리 import 금지")


class SupabaseBoundaryTest(unittest.TestCase):
    """관례 2 — Supabase 쿼리 빌더는 저장소 경계 안에만 둔다."""

    # 경계로 인정하는 곳. 파이프라인의 db.py, fundamentals의 책임별 저장소,
    # 싱글턴 자체와 저장소 경계 안의 도메인 db.py.
    ALLOWED_SUFFIXES = ("/db.py",)
    ALLOWED_DIRS = ("src/investment_agent/data/fundamentals/infrastructure/supabase/",)
    ALLOWED_FILES = {
        "src/investment_agent/platform/db/postgres.py",
        "src/investment_agent/data/macro/releases/commands/econ_calendar_publish_ics.py",  # Storage 업로드, 쿼리 빌더 아님
    }

    def test_query_builder_stays_inside_the_repository_layer(self) -> None:
        offenders = []
        for path in _modules():
            posix = _posix(path)
            if (
                posix.endswith(self.ALLOWED_SUFFIXES)
                or posix.startswith(self.ALLOWED_DIRS)
                or posix in self.ALLOWED_FILES
            ):
                continue
            for node in ast.walk(_tree(path)):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if node.func.attr not in {"table", "rpc"}:
                    continue
                root = node.func.value
                while isinstance(root, (ast.Attribute, ast.Call)):
                    root = root.func if isinstance(root, ast.Call) else root.value
                if isinstance(root, ast.Name) and root.id == "sb":
                    offenders.append(f"{posix}:{node.lineno}")
        self.assertEqual([], offenders, "Supabase 쿼리는 platform/db/postgres.py 안에서만")


class PresentationLayerDirectionTest(unittest.TestCase):
    """대시보드는 도메인 구현 대신 공개된 읽기 계약만 소비한다.

    아래 목록은 허용 목록이 아니라 아직 ``investment_agent.reporting`` 계약으로 옮기지 못한
    의존성 부채다. 새 의존성도, 이미 제거한 항목이 목록에 남는 것도 실패시켜
    리디자인 기간 동안 목록이 줄기만 하게 한다.
    """

    DASHBOARD_ROOT = "src/investment_agent/dashboard/"
    PENDING_DEPENDENCIES = frozenset(
        {
            ("src/investment_agent/dashboard/app_pages/earnings.py", "investment_agent.notifications.earnings_report"),
            ("src/investment_agent/dashboard/app_pages/ml_rl_lab.py", "investment_agent.trading.decision.signal_blender"),
            ("src/investment_agent/dashboard/calculations/strategy.py", "investment_agent.research.strategies.strategies"),
            ("src/investment_agent/dashboard/calculations/tech.py", "investment_agent.research.features.compute"),
        }
    )

    def test_dashboard_domain_dependencies_only_shrink(self) -> None:
        found: set[tuple[str, str]] = set()
        for path in _modules(SRC / "investment_agent" / "dashboard"):
            posix = _posix(path)
            for module in _imported_modules(path):
                # `bootstrap`은 도메인 구현이 아니라 진입점의 `.env` 로더다. 대시보드도
                # 진입점이므로 이것을 부르는 것이 맞다 — 안 부르면 모든 화면이
                # "필수 연결 설정이 없습니다"로만 뜬다.
                if module.startswith(("investment_agent.dashboard", "investment_agent.platform",
                                      "investment_agent.reporting", "investment_agent.bootstrap")):
                    continue
                # 검사 대상은 `investment_agent.*` 절대 경로다. 접두어를 잘못 잡으면
                # 위반이 하나도 안 걸리면서 테스트는 초록으로 남는다.
                if module.startswith("investment_agent."):
                    found.add((posix, module))

        def fmt(pairs: set[tuple[str, str]]) -> list[str]:
            return sorted(f"{path} -> {module}" for path, module in pairs)

        self.assertEqual(
            [],
            fmt(found - self.PENDING_DEPENDENCIES),
            "새 presentation 계층 위반. dashboard가 도메인 구현을 직접 가져오지 않게 하세요",
        )
        self.assertEqual(
            [],
            fmt(self.PENDING_DEPENDENCIES - found),
            "해소된 presentation 계층 부채를 PENDING_DEPENDENCIES에서 지우세요",
        )


class DangerFloorTest(unittest.TestCase):
    """CLAUDE.md와 AGENTS.md의 안전 바닥이 어긋나지 않는지 본다.

    두 문서에 같은 블록을 두는 것은 SSOT 원칙의 예외다. 그럴 값어치가 있는 이유는
    Claude Code만 CLAUDE.md를 자동으로 읽고, Codex·Antigravity는 AGENTS.md만 읽기
    때문이다 — 링크를 따라가 주기를 바라는 것으로는 되돌릴 수 없는 실수를 막지 못한다.

    복제를 허용하는 대신 드리프트를 불가능하게 만든다. 한쪽만 고치면 여기서 걸린다.
    """

    START = "<!-- danger-floor:start -->"
    END = "<!-- danger-floor:end -->"

    def _floor(self, name: str) -> str:
        text = Path(name).read_text(encoding="utf-8")
        self.assertIn(self.START, text, f"{name}: 안전 바닥 시작 표시가 없다")
        self.assertIn(self.END, text, f"{name}: 안전 바닥 끝 표시가 없다")
        return text.split(self.START, 1)[1].split(self.END, 1)[0].strip()

    def test_claude_md_and_agents_md_carry_the_same_floor(self) -> None:
        self.assertEqual(
            self._floor("CLAUDE.md"),
            self._floor("AGENTS.md"),
            "안전 바닥이 어긋났다 — 한쪽만 고치지 말고 두 파일을 같이 고치세요",
        )

    def test_the_floor_is_short_enough_to_actually_be_read(self) -> None:
        """길어지면 아무도 안 읽는다. 늘리고 싶으면 스킬이나 CLAUDE.md 본문으로."""
        floor = self._floor("CLAUDE.md")
        bullets = [ln for ln in floor.splitlines() if ln.startswith("- ")]
        self.assertLessEqual(len(bullets), 10, "안전 바닥이 10줄을 넘었다")


class CodexSkillIndexTest(unittest.TestCase):
    """Codex는 스킬을 자동 발견하지 않는다 — AGENTS.md가 전부 가리켜야 한다."""

    def test_agents_md_points_at_every_installed_codex_skill(self) -> None:
        skills = sorted(
            d.name for d in Path(".codex/skills").iterdir()
            if (d / "SKILL.md").exists()
        )
        self.assertTrue(skills, ".codex/skills 에 스킬이 없다")
        text = Path("AGENTS.md").read_text(encoding="utf-8")
        missing = [s for s in skills if f".codex/skills/{s}/SKILL.md" not in text]
        self.assertEqual([], missing, "AGENTS.md가 가리키지 않는 스킬 — Codex는 이것을 못 본다")

    def test_claude_and_codex_skills_do_not_drift(self) -> None:
        """두 도구가 같은 규칙을 받아야 한다. 한쪽에만 스킬이 있으면 지침이 갈린다."""
        claude = {d.name for d in Path(".claude/skills").iterdir() if (d / "SKILL.md").exists()}
        codex = {d.name for d in Path(".codex/skills").iterdir() if (d / "SKILL.md").exists()}
        self.assertEqual(claude, codex, "스킬 목록이 도구마다 다르다")


class SchemaOwnershipTest(unittest.TestCase):
    """CLAUDE.md 관례 2 — 각 저장소는 자신이 소유한 스키마만 직접 조회한다."""

    # 파일 -> 그 파일이 조회해도 되는 스키마 상수 이름
    OWNED_SCHEMAS = {
        "src/investment_agent/trading/supabase_repository.py": {"_SCHEMA"},
    }

    def test_repositories_query_only_the_schema_they_own(self) -> None:
        offenders: list[str] = []
        for posix, allowed in sorted(self.OWNED_SCHEMAS.items()):
            source = Path(posix).read_text(encoding="utf-8")
            for name in set(re.findall(r"\bsb\.schema\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", source)):
                # 지역 변수로 스키마를 받는 공용 헬퍼는 제외한다.
                if name in allowed or name.islower():
                    continue
                offenders.append(f"{posix} -> {name}")
        self.assertEqual(
            [],
            sorted(offenders),
            "남의 스키마를 직접 조회합니다. 그 스키마의 owner 모듈에 조회를 두고 위임하세요",
        )


if __name__ == "__main__":
    unittest.main()
