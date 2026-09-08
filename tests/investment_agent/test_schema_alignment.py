"""저장소가 부르는 컬럼이 v1 선언 SQL에 실제로 있는지 본다.

## 왜 이 검사가 필요한가

없는 컬럼을 select하면 PostgREST는 오류를 주지만, `eq`/`order`의 컬럼 이름이 틀리면
**조건이 안 맞는 것과 구분되지 않는 빈 결과**가 나온다. 실제로 macro 저장소가
`snapshot_at`을 읽고 있었는데 스키마의 이름은 `collected_at`이었다 — 라이브에 붙였다면
"다가오는 발표가 없다"는 답을 조용히 계속 받았을 것이다.

## 무엇을 비교하나

각 저장소 모듈의 `SCHEMA` 상수가 가리키는 스키마의 **모든 컬럼**을 모아, 그 모듈이
쿼리에서 이름으로 부르는 컬럼이 그 안에 있는지 본다. 어느 표의 컬럼인지까지 맞추지는
않는다 — 그러려면 쿼리 흐름을 따라가야 하고, 그 추적기 자체가 검증이 필요한 물건이
된다. 오타와 이름 드리프트를 잡는 데는 이 정도로 충분하다.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V1_SQL = ROOT / "db" / "postgres" / "v1"
PACKAGE = ROOT / "src" / "investment_agent"

# 컬럼 이름 자리에 오는 인자를 갖는 호출.
_COLUMN_ARG_CALLS = {"eq", "neq", "gt", "gte", "lt", "lte", "in_", "is_", "order", "not_"}

# 컬럼 이름이 키워드 인자로 넘어가는 자리.
_COLUMN_KEYWORDS = {"columns", "filter_column", "order_by", "on_conflict"}

# PostgREST 임베디드 리소스 표기: `securities(ticker)`.
_EMBEDDED = re.compile(r"\w+\s*\([^)]*\)")

_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(?P<schema>\w+)\.(?P<table>\w+)\s*\((?P<body>.*?)\n\);",
    re.IGNORECASE | re.DOTALL,
)
_VIEW_RE = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+VIEW\s+(?P<schema>\w+)\.(?P<view>\w+)",
    re.IGNORECASE,
)

# 컬럼 선언이 아닌 줄의 시작 낱말.
_NOT_A_COLUMN = {
    "constraint", "primary", "unique", "check", "foreign", "exclude", "like", "--",
}


def _columns_of_body(body: str) -> set[str]:
    columns: set[str] = set()
    depth = 0
    for raw in body.splitlines():
        line = raw.strip()
        # 여러 줄에 걸친 CHECK 안쪽은 컬럼 선언이 아니다.
        opening, closing = line.count("("), line.count(")")
        if depth > 0:
            depth += opening - closing
            continue
        if not line or line.startswith("--"):
            continue
        first = line.split()[0].lower().rstrip(",")
        if first in _NOT_A_COLUMN:
            depth += opening - closing
            continue
        columns.add(line.split()[0].strip(","))
        depth += opening - closing
    return columns


def schema_columns() -> dict[str, set[str]]:
    """스키마별 컬럼 이름 전부. 뷰가 있는 스키마는 검사에서 제외한다(뷰는 파싱하지 않는다)."""
    columns: dict[str, set[str]] = {}
    for path in sorted(V1_SQL.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for match in _TABLE_RE.finditer(text):
            columns.setdefault(match.group("schema"), set()).update(
                _columns_of_body(match.group("body"))
            )
    return columns


def _string_parts(node: ast.AST) -> list[str]:
    """상수 문자열과 f-string의 **리터럴 조각**을 모은다."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [
            part.value for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        ]
    # 괄호로 묶어 여러 줄에 나눠 쓴 문자열은 파서가 이미 하나로 합쳐 준다. 남는 것은
    # 명시적인 `+` 연결뿐이다.
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _string_parts(node.left) + _string_parts(node.right)
    return []


def _named_constant(node: ast.AST, constants: dict[str, str]) -> list[str]:
    """`select(_PRICE_COLUMNS)`처럼 상수로 넘긴 컬럼 목록을 펼친다."""
    if isinstance(node, ast.Name) and node.id in constants:
        return [constants[node.id]]
    return []


def _column_tokens(text: str) -> set[str]:
    cleaned = _EMBEDDED.sub("", text)
    tokens = set()
    for piece in cleaned.split(","):
        name = piece.strip()
        if re.fullmatch(r"[a-z_][a-z0-9_]*", name):
            tokens.add(name)
    return tokens


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """모듈 최상단의 문자열 상수.

    컬럼 목록은 대개 `_PRICE_COLUMNS` 같은 상수로 빠져 있다. 그것을 못 따라가면
    이 검사가 정작 가장 큰 select를 건너뛴다 — 실제로 market 저장소는 5개만
    검사되고 있었다.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        parts = _string_parts(node.value)
        if parts:
            constants[target.id] = "".join(parts)
    return constants


def referenced_columns(path: Path) -> set[str]:
    """이 모듈이 쿼리에서 이름으로 부르는 컬럼."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = _module_constants(tree)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attribute = node.func.attr
        if attribute == "select":
            for part in node.args[:1]:
                for text in _string_parts(part) or _named_constant(part, constants):
                    names |= _column_tokens(text)
        elif attribute in _COLUMN_ARG_CALLS and node.args:
            for text in _string_parts(node.args[0]):
                names |= _column_tokens(text)
        # `select_in_chunks(columns=..., filter_column=..., order_by=...)`와
        # `upsert(on_conflict=...)`. 컬럼 이름이 키워드 인자로 가는 자리가 실제로 더 많다.
        for keyword in node.keywords:
            if keyword.arg not in _COLUMN_KEYWORDS:
                continue
            for text in _string_parts(keyword.value) or _named_constant(keyword.value, constants):
                names |= _column_tokens(text)
    return names


def _declared_schema(path: Path) -> str | None:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SCHEMA" for target in node.targets
        ):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    return None


# Supabase가 아닌 저장소. 이 가드는 db/postgres/v1 선언과 PostgREST 컬럼 이름을 맞춰보는
# 물건이라, 로컬 DuckDB에 raw SQL을 쓰는 저장소에는 전제가 성립하지 않는다.
# 조건으로 거르지 않고 이름을 적는다 — 조건으로 거르면 SCHEMA를 빠뜨린 Supabase
# 저장소까지 조용히 빠져나간다.
LOCAL_STORE_REPOSITORIES = frozenset({
    "src/investment_agent/intelligence/repository.py",
    "src/investment_agent/research/storage/repository.py",
    "src/investment_agent/trading/repository.py",
})


class SchemaAlignmentTest(unittest.TestCase):
    def _repositories(self) -> list[Path]:
        found = [
            path
            for path in sorted(PACKAGE.rglob("repository.py"))
            if path.relative_to(ROOT).as_posix() not in LOCAL_STORE_REPOSITORIES
        ]
        # 저장소를 하나도 못 찾으면 이 검사는 아무것도 지키지 않는다.
        self.assertTrue(found, "repository 모듈을 하나도 찾지 못했다")
        return found

    def test_every_exempt_repository_still_exists(self) -> None:
        """목록이 낡으면 가드의 적용 범위가 조용히 넓어지거나 좁아진다."""
        missing = sorted(
            path for path in LOCAL_STORE_REPOSITORIES if not (ROOT / path).is_file()
        )
        self.assertEqual([], missing, "예외 목록에 없는 파일이 남아 있다")

    def test_v1_sql_declares_the_schemas_we_query(self) -> None:
        declared = schema_columns()
        self.assertTrue(declared, "db/postgres/v1에서 표를 하나도 읽지 못했다")
        for path in self._repositories():
            schema = _declared_schema(path)
            with self.subTest(module=path.name, schema=schema):
                self.assertIsNotNone(schema, f"{path}: SCHEMA 상수가 없다")
                self.assertIn(schema, declared)

    def test_every_queried_column_exists_in_its_schema(self) -> None:
        declared = schema_columns()
        offenders: list[str] = []
        for path in self._repositories():
            schema = _declared_schema(path)
            if schema not in declared:
                continue
            for column in sorted(referenced_columns(path) - declared[schema]):
                offenders.append(f"{path.relative_to(ROOT)}: {schema}.{column}")
        self.assertEqual([], sorted(offenders))

    def test_the_parser_actually_reads_columns(self) -> None:
        """파서가 빈 집합을 돌려주면 위 검사는 아무것도 확인하지 않는다."""
        declared = schema_columns()
        self.assertIn("security_id", declared["universe"])
        self.assertIn("collected_at", declared["macro"])
        self.assertIn("accession_no", declared["fundamentals"])
        # CHECK 안쪽 낱말이 컬럼으로 새어 들어오면 검사가 헐거워진다.
        self.assertNotIn("btrim", declared["universe"])
        self.assertNotIn("jsonb_typeof", declared["universe"])

    # 저장소 하나가 실제로 부르는 컬럼 수의 하한. 추출기가 상수를 못 따라가면
    # 이 수가 뚝 떨어지고, 그때 위 검사는 아무것도 안 지키면서 통과한다.
    MINIMUM_COLUMNS = 8

    def test_repositories_reference_enough_columns_to_be_meaningful(self) -> None:
        for path in self._repositories():
            with self.subTest(module=str(path.relative_to(ROOT))):
                self.assertGreaterEqual(len(referenced_columns(path)), self.MINIMUM_COLUMNS)


if __name__ == "__main__":
    unittest.main()
