"""정적으로 해석 가능한 조회를 스키마 합집합이 아닌 개별 테이블과 대조한다."""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def declared_columns():
    tables = {}
    for path in (ROOT / "db/postgres/v1").glob("*.sql"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+\.\w+)\s*\((.*?)\n\);", text, re.S):
            tables[match[1]] = set(re.findall(
                r"^\s{2}(\w+)\s+(?:text|bigint|int|integer|smallint|boolean|bool|double|numeric|jsonb|date|time|uuid|bytea|real|varchar)",
                match[2], re.M | re.I,
            ))
    return tables


def query_issues(source, tables):
    tree = ast.parse(source)
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for name in node.targets:
                if isinstance(name, ast.Name):
                    constants[name.id] = node.value.value

    def value(node):
        if isinstance(node, ast.Constant):
            return node.value
        return constants.get(node.id) if isinstance(node, ast.Name) else None

    def table_of(node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            return None
        if node.func.attr == "table":
            if len(node.args) == 2:
                return f"{value(node.args[0])}.{value(node.args[1])}"
            parent = node.func.value
            if (node.args and isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute)
                    and parent.func.attr == "schema" and parent.args):
                return f"{value(parent.args[0])}.{value(node.args[0])}"
        return table_of(node.func.value)

    issues = []
    for node in ast.walk(tree):
        if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute)
                or node.func.attr not in {"select", "eq", "gte", "lte", "gt", "lt", "order", "in_", "is_"}
                or not node.args):
            continue
        table = table_of(node.func.value)
        selected = value(node.args[0])
        if table not in tables or not isinstance(selected, str):
            continue
        columns = [column.strip() for column in selected.split(",")]
        # join·별칭·동적 builder는 이 검사 범위가 아니며 각 owner 동작 테스트로 검증한다.
        if any(not re.fullmatch(r"[a-z_][a-z_0-9]*", column) for column in columns):
            continue
        missing = set(columns) - tables[table]
        if missing:
            issues.append((node.lineno, table, sorted(missing)))
    return issues


class TableQueryContractsTest(unittest.TestCase):
    def test_column_on_another_table_does_not_make_query_valid(self):
        tables = {"universe.entities": {"cik"}, "universe.securities": {"cik", "is_tracked"}}
        source = 'sb.schema("universe").table("entities").select("cik").eq("is_tracked", True)'
        self.assertEqual([(1, "universe.entities", ["is_tracked"])], query_issues(source, tables))

    def test_static_queries_match_their_table(self):
        tables = declared_columns()
        self.assertEqual(25, len(tables))
        issues = []
        for path in (ROOT / "src").rglob("*.py"):
            issues.extend((str(path.relative_to(ROOT)), *issue)
                          for issue in query_issues(path.read_text(encoding="utf-8"), tables))
        self.assertEqual([], issues)
