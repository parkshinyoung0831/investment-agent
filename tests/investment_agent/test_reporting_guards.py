"""읽기 경계와 SQL 공개 계약. 각 가드에 위반을 하나씩 주입해 실패도 검증한다."""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
import re
import unittest

from investment_agent.reporting.readers.runtime import LOCAL_VIEWS
from investment_agent.reporting.readers.financial import VIEWS

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src/investment_agent/reporting"
SQL = ROOT / "db/postgres/v1/90_reporting.sql"
ALLOWED_IMPORTS = {
    "investment_agent.reporting.notifications.investment.performance",
    "__future__", "os", "re", "json", "dataclasses", "datetime", "typing", "collections.abc", "types", "pandas", "pathlib",
    "investment_agent.platform.db.postgres", "investment_agent.research.storage.repository", "investment_agent.platform.cache",
    "investment_agent.platform.db.sqlite",
    "investment_agent.reporting.models", "investment_agent.reporting.services.strategy_labels",
    "investment_agent.reporting.services.investment",
    "investment_agent.intelligence.infrastructure.sources.news.provider",
    "investment_agent.intelligence.infrastructure.sources.news",
    "investment_agent.data.institutional.domain.managers",
    "investment_agent.reporting.readers.financial", "investment_agent.reporting.readers.runtime",
    "investment_agent.reporting.services.economic_releases", "investment_agent.reporting.services.macro.constants", "investment_agent.reporting.readers.research",
    "investment_agent.intelligence.infrastructure.db", "investment_agent.intelligence.repository",
    "investment_agent.intelligence.infrastructure.sources.news.provider", "investment_agent.platform.clock",
    "investment_agent.platform.db.duckdb", "investment_agent.platform.logging",
    "investment_agent.data.macro.domain.releases.identity",
    "investment_agent.data.macro.domain.releases.release_catalog",
    "investment_agent.data.fundamentals.domain.services.classify_dimensions",
    "investment_agent.data.fundamentals.domain.taxonomy.segment_concepts",
    "investment_agent.research.strategies.catalog",
    "itertools",
    "investment_agent.reporting.readers.select_only",
    "investment_agent.reporting.services.fundamental_segments",
}
WRITE_CALLS = {"insert", "upsert", "update", "delete", "rpc", "execute", "from_config", "create_client"}


def _inside_method(node, parents, class_name, method):
    """`node`가 `class_name.method` 본문(중첩 함수 포함) 안에 있는지 본다."""
    current, in_method = node, False
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.FunctionDef) and current.name == method:
            in_method = True
        if isinstance(current, ast.ClassDef) and current.name == class_name:
            return in_method
    return False


def assert_boundary(sources):
    for filename, source in sources.items():
        tree = ast.parse(source)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name in ALLOWED_IMPORTS for a in node.names), filename
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0 and node.module in ALLOWED_IMPORTS, filename
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in {"__import__", "eval", "exec", "open"}, filename
                if isinstance(node.func, ast.Attribute):
                    if filename == "readers/select_only.py":
                        # SELECT 전용 gateway. 조회는 항상 `.table(...).select(...)`로 시작하고, 종단 `.execute()`는
                        # `SelectOnlyGateway.select_rows` 안에만 있다. insert·upsert·update·delete·rpc는 아래 검사가 막는다.
                        if node.func.attr == "table":
                            parent = parents.get(node)
                            assert isinstance(parent, ast.Attribute) and parent.attr == "select", filename
                            continue
                        if node.func.attr == "execute":
                            assert _inside_method(node, parents, "SelectOnlyGateway", "select_rows"), filename
                            continue
                    if (
                        filename == "readers/earnings.py"
                        and node.func.attr == "update"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "value"
                    ):
                        continue  # 행 사본(dict) 병합이며 저장소 쓰기가 아니다.
                    if (
                        filename == "readers/runtime.py"
                        and node.func.attr == "update"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id in {"model", "decision", "row"}
                    ):
                        continue
                    if node.func.attr == "execute" and filename == "readers/runtime.py":
                        # sqlite3 connection.execute()는 postgrest 빌더의 종단 호출이 아니다 —
                        # SELECT를 helper 인자로 넘기거나 PRAGMA를 쓸 수 있다. helper의
                        # `sql` 인자와 직접 전달한 SELECT/PRAGMA만 허용한다.
                        argument = node.args[0] if node.args else None
                        if isinstance(argument, ast.Name):
                            assert argument.id == "sql", filename
                        else:
                            text = ast.get_source_segment(sources[filename], argument) or ""
                            assert re.match(r"\s*f?[\"'](?:SELECT|PRAGMA)\b", text, re.I), filename
                        continue
                    assert node.func.attr not in WRITE_CALLS, filename
                    if node.func.attr == "table":
                        assert filename == "readers/financial.py", filename
                        assert isinstance(node.args[0], ast.Name) and node.args[0].id == "SCHEMA", filename
            if isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == "SCHEMA" for t in node.targets):
                    assert ast.literal_eval(node.value) == "reporting", filename


def view_columns(sql):
    # SELECT 목록만 읽는다. 중첩 함수와 window의 쉼표/FROM은 분리자로 쓰지 않는다.
    sql = re.sub(r"--[^\n]*", "", sql)
    result = {}
    for match in re.finditer(r"CREATE OR REPLACE VIEW reporting\.(\w+) WITH \(security_invoker = true\) AS\s+SELECT\s+", sql):
        text = sql[match.end():]
        text = re.sub(r"^DISTINCT ON \([^)]*\)\s*", "", text)
        depth = 0
        end = 0
        for i, char in enumerate(text):
            if depth == 0 and text[i:i+5] == "FROM ":
                end = i
                break
            depth += (char == "(") - (char == ")")
        assert end, match.group(1)
        pieces = []
        depth = start = 0
        for i, char in enumerate(text[:end]):
            if char == "," and depth == 0:
                pieces.append(text[start:i].strip())
                start = i + 1
            depth += (char == "(") - (char == ")")
        pieces.append(text[start:end].strip())
        names = []
        for piece in pieces:
            alias = re.search(r"\bAS\s+(\w+)\s*$", piece, re.I)
            if alias:
                names.append(alias.group(1))
            else:
                assert re.fullmatch(r"\w+\.\w+", piece), piece
                names.append(piece.split(".")[1])
        result[match.group(1)] = names
    return result


# 코드 계약(VIEWS)이 아닌 뷰. 다른 뷰가 조합해 쓰는 내부 뷰와, 사람이 직접 여는 6개 뷰다.
_INTERNAL_VIEWS = {"macro_observation_history"}
HUMAN_VIEWS = {
    "security_overview", "financial_statements", "earnings_outlook",
    "earnings_surprises", "economic_calendar", "institutional_holdings",
}


def assert_contract(specs, sql):
    declared = {view: columns for view, columns in view_columns(sql).items()
                if view not in _INTERNAL_VIEWS | HUMAN_VIEWS}
    assert len(declared) == len(specs)
    assert set(specs) == set(declared)
    for view, spec in specs.items():
        assert spec.columns.split(",") == declared[view], view
        assert spec.order_by and set(spec.order_by.split(",")) <= set(declared[view]), view
        assert spec.time_column is None or spec.time_column in declared[view], view
        assert spec.scope_column is None or spec.scope_column in declared[view], view


class ReportingGuardsTest(unittest.TestCase):
    def test_read_only_dependency_boundary(self):
        """reporting 전체가 읽기 전용인지 본다 — 한 파일만 빠져도 그 경로로 쓰기가 샌다."""
        # 주제별 하위 패키지(earnings/macro/investment)와 알림 read model은 각자
        # 자기 테스트가 있다. 여기서는 저장소를 여는 readers와 평면 services를 본다.
        subject_packages = ("services/earnings/", "services/macro/",
                            "services/investment/", "notifications/")
        sources = {
            name: path.read_text(encoding="utf-8")
            for path in PACKAGE.rglob("*.py")
            for name in (path.relative_to(PACKAGE).as_posix(),)
            if not name.startswith(subject_packages)
        }
        self.assertEqual(
            {
                "__init__.py", "models.py",
                "readers/__init__.py", "readers/dashboard.py", "readers/financial.py",
                "readers/ai.py", "readers/earnings.py", "readers/intelligence.py", "readers/news.py",
                "readers/research.py", "readers/runtime.py", "readers/select_only.py",
                "services/__init__.py", "services/economic_releases.py",
                "services/financial_row.py", "services/fundamental_segments.py", "services/strategy_labels.py",
            },
            set(sources),
        )
        assert_boundary(sources)

    def test_every_view_column_matches_sql(self):
        """LOCAL_VIEWS는 실제 Postgres 뷰가 아니라 로컬 runtime.sqlite3 읽기라
        90_reporting.sql에 선언되지 않는다."""
        remote_views = {view: spec for view, spec in VIEWS.items() if view not in LOCAL_VIEWS}
        assert_contract(remote_views, SQL.read_text(encoding="utf-8"))

    def assert_guard_fails(self, callback):
        # 실제 unittest 실행 결과가 failure인지 확인한다. 문법 오류는 성공으로 세지 않는다.
        result = unittest.TestResult()
        unittest.FunctionTestCase(callback).run(result)
        self.assertEqual(1, len(result.failures), result.errors)
        self.assertEqual([], result.errors)

    def test_boundary_rejects_individual_injected_violations(self):
        for statement in (
            "import investment_agent.dashboard", "from investment_agent.data.market import persistence",
            "from investment_agent.notifications import service", "import yfinance",
            "from ..trading import repository", "import requests", "import streamlit",
            "db.insert({})", "db.upsert({})", "db.update({})", "db.delete()", "db.rpc('x')",
            "query.execute()", "Database.from_config(config)", "__import__('requests')",
            "SCHEMA = 'execution'", "db.table('execution', 'orders')",
        ):
            with self.subTest(statement=statement):
                self.assert_guard_fails(lambda: assert_boundary({"queries.py": statement}))

    def test_select_only_gateway_exceptions_stay_narrow(self):
        """gateway 예외(`.table().select()`·`select_rows`의 `.execute()`)는 그 자리에서만 통한다."""
        gateway = (
            "class SelectOnlyGateway:\n"
            "    def select_rows(self):\n"
            "        query = self.s.table('a').select('x')\n"
            "        return query.execute()\n"
        )
        assert_boundary({"readers/select_only.py": gateway})
        violations = (
            gateway + "    def other(self):\n        return self.q.execute()\n",
            "class SelectOnlyGateway:\n    def select_rows(self):\n        return self.s.table('a').insert({})\n",
            "class SelectOnlyGateway:\n    def select_rows(self):\n        return self.s.table('a').select('x').upsert({})\n",
            "class SelectOnlyGateway:\n    def select_rows(self):\n        return self.s.rpc('f')\n",
        )
        for statement in violations:
            with self.subTest(statement=statement):
                self.assert_guard_fails(lambda: assert_boundary({"readers/select_only.py": statement}))
        # 다른 파일은 같은 코드를 쓸 수 없다.
        self.assert_guard_fails(lambda: assert_boundary({"readers/ai.py": gateway}))

    def test_contract_rejects_individual_injected_violations(self):
        remote_views = {view: spec for view, spec in VIEWS.items() if view not in LOCAL_VIEWS}
        base = remote_views["prices_daily"]
        mutations = [
            replace(base, columns=base.columns.replace("trade_date", "missing_date")),
            replace(base, order_by="missing_key"), replace(base, order_by=""),
            replace(base, time_column="missing_time"), replace(base, scope_column="missing_scope"),
        ]
        sql = SQL.read_text(encoding="utf-8")
        for changed in mutations:
            with self.subTest(spec=changed):
                specs = dict(remote_views) | {"prices_daily": changed}
                self.assert_guard_fails(lambda: assert_contract(specs, sql))
        specs = dict(remote_views)
        del specs["prices_daily"]
        self.assert_guard_fails(lambda: assert_contract(specs, sql))
        self.assert_guard_fails(lambda: assert_contract(remote_views, sql.replace("p.trade_date,", "p.missing_date,")))


class HumanViewTest(unittest.TestCase):
    """사람이 여는 뷰는 이름을 영문으로 두고 뜻을 한국어 COMMENT로 적는다."""

    def test_every_human_view_and_column_has_a_korean_comment(self) -> None:
        sql = SQL.read_text(encoding="utf-8")
        columns = view_columns(sql)
        for view in sorted(HUMAN_VIEWS):
            with self.subTest(view=view):
                self.assertIn(f"COMMENT ON VIEW reporting.{view} IS '[", sql)
                for column in columns[view]:
                    self.assertIn(f"COMMENT ON COLUMN reporting.{view}.{column} IS", sql)

    def test_human_views_do_not_need_quoted_identifiers(self) -> None:
        sql = SQL.read_text(encoding="utf-8")
        start = sql.index("-- 사람이 여는 뷰")
        self.assertNotRegex(sql[start:], r' AS "')
