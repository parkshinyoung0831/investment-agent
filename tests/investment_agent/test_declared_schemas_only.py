"""코드가 부르는 Postgres 스키마는 선언에 실재해야 한다.

이 저장소의 단위 테스트는 DB를 때리지 않는다. 그래서 없는 스키마를 부르는 코드가
있어도 초록이고, 운영에서 `PGRST106 Invalid schema`로만 드러난다 — 실제로
`trading` 스키마를 읽는 경로가 하나 남아 있었고, Data API가 통째로 닫혀 있는 동안
같은 오류에 섞여 보이지 않았다.

`db/postgres/v1/*.sql`이 선언의 단일 기준이다. 다만 `"trading"` 같은 이름은
로컬 SQLite 원장(`trading/local_store.py`)의 **논리 네임스페이스**로도 쓰이므로,
문자열만 보면 안 된다. 여기서는 **Postgres service 싱글턴 `sb`를 import한 모듈**로
한정한다 — 그 모듈이 부르는 스키마는 반드시 Postgres에 실재해야 한다.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "investment_agent"
SQL_DIR = ROOT / "db" / "postgres" / "v1"

#: 선언이 아니라 다른 저장소를 가리키는 이름. 문자열이 같아도 Postgres가 아니다.
_NOT_POSTGRES = frozenset({"public", "graphql_public", "main", "memory", "temp"})


def _declared_schemas() -> set[str]:
    found: set[str] = set()
    for path in sorted(SQL_DIR.glob("*.sql")):
        found |= set(re.findall(r"CREATE SCHEMA IF NOT EXISTS\s+([a-z_]+)",
                                path.read_text(encoding="utf-8")))
    return found


def _imports_postgres_singleton(tree: ast.Module) -> bool:
    """`sb`는 service-role Postgres 클라이언트다. 이것을 들여온 모듈만 대상이다."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("db.postgres"):
            if any(alias.name == "sb" for alias in node.names):
                return True
    return False


def _schema_constants(tree: ast.Module) -> dict[str, str]:
    """모듈 최상단의 `SCHEMA*= "이름"` 상수. 규칙 16 때문에 리터럴은 여기에만 있다."""
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name) and re.fullmatch(r"_?SCHEMA(_[A-Z0-9_]+)?", target.id):
                found[target.id] = value.value
    return found


def _called_schemas() -> dict[str, list[str]]:
    """`schema=...` 키워드와 `.schema(...)` 호출에서 확정 가능한 이름을 모은다."""
    calls: dict[str, list[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover
            continue
        if not _imports_postgres_singleton(tree):
            continue
        constants = _schema_constants(tree)

        def resolve(node: ast.expr) -> str | None:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.Name):
                return constants.get(node.id)
            return None

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            names: list[str] = []
            for keyword in node.keywords:
                if keyword.arg == "schema":
                    names.append(resolve(keyword.value) or "")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "schema"                     and len(node.args) == 1:
                names.append(resolve(node.args[0]) or "")
            for name in names:
                if name and name not in _NOT_POSTGRES:
                    calls.setdefault(name, []).append(
                        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    return calls


class CodeOnlyCallsDeclaredSchemasTest(unittest.TestCase):
    def test_every_schema_literal_exists_in_the_declaration(self) -> None:
        declared = _declared_schemas()
        offenders = [
            f"{name} <- {', '.join(sorted(set(sites))[:4])}"
            for name, sites in sorted(_called_schemas().items())
            if name not in declared
        ]
        self.assertEqual([], offenders)

    def test_the_scan_sees_the_real_schemas(self) -> None:
        """대상을 못 찾으면 위 테스트는 공허하게 통과한다."""
        declared = _declared_schemas()
        self.assertEqual(
            {"universe", "market", "fundamentals", "macro", "institutional", "reporting"},
            declared,
        )
        called = set(_called_schemas())
        self.assertTrue({"universe", "market", "fundamentals"} <= called, sorted(called))
        # 논리 네임스페이스는 대상이 아니다 — `sb`를 안 쓰는 모듈이므로.
        self.assertNotIn("trading", called)


if __name__ == "__main__":
    unittest.main()
