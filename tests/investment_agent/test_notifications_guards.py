"""알림의 도메인/DB/HTTP 경계와 선언 SQL 계약. 위반 주입도 함께 실행한다."""
from __future__ import annotations

import ast
import re
from pathlib import Path
import unittest

from tests.investment_agent.test_schema_alignment import _columns_of_body

ROOT = Path(__file__).resolve().parents[2]
_SQLITE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(?P<table>\w+)\s*\((?P<body>.*?)\n\);",
    re.IGNORECASE | re.DOTALL,
)
PACKAGE = ROOT / "src/investment_agent/notifications"
ALLOWED_ROOTS = {
    "__future__", "copy", "dataclasses", "datetime", "typing", "collections", "math",
    "json", "urllib", "statistics", "os", "asyncio", "shutil", "argparse", "re",
    "tempfile", "pathlib", "playwright", "jinja2", "zoneinfo", "time",
}
INTERNAL = ("investment_agent.notifications", "investment_agent.reporting",
            "investment_agent.platform", "investment_agent.config",
            "investment_agent.data.institutional",
            # research 산출물은 research가 소유하는 읽기 계약으로만 본다.
            "investment_agent.research.strategies", "investment_agent.research.storage",
            "investment_agent.bootstrap")
DB_METHODS = {"table", "rpc", "select_paged", "insert_ignore_duplicate"}


def assert_boundary(sources):
    for filename, source in sources.items():
        tree = ast.parse(source)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    assert node.level == 1, filename
                    continue
                names = [node.module or ""]
            for name in names:
                if name == "requests":
                    assert filename == "channels/discord.py", filename
                else:
                    assert name.split(".")[0] in ALLOWED_ROOTS or any(
                        name == prefix or name.startswith(prefix + ".") for prefix in INTERNAL
                    ), (filename, name)
                if name == "investment_agent.platform.db.postgres":
                    assert filename in {"outbox.py", "subscriptions.py"}, filename
                if filename.startswith("renderers/"):
                    assert not name.startswith("investment_agent.notifications.service"), filename
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in {"__import__", "eval", "exec"}, filename
                if isinstance(node.func, ast.Attribute):
                    attr = node.func.attr
                    assert attr not in {"delete", "rpc", "schema", "from_config", "create_client"}, filename
                    if attr in DB_METHODS or attr == "execute":
                        assert filename in {"outbox.py", "subscriptions.py"}, filename
                    if attr == "table":
                        assert isinstance(node.args[0], ast.Name) and node.args[0].id == "SCHEMA", filename
                        assert isinstance(node.args[1], ast.Name) and node.args[1].id in {
                            "T_OUTBOX", "T_DELIVERIES", "TABLE",
                        }, filename


def assert_schema_contract(source, sql):
    """outbox.py가 삽입하는 컬럼이 로컬 runtime SQLite 선언에 실제로 있는지 본다.

    outbox·deliveries는 ``notifications`` Supabase 스키마가 아니라
    ``data/local/runtime/runtime.sqlite3``(``db/sqlite/runtime/v1/40_notifications.sql``)가 소유한다 —
    실행 컴퓨터별 알림 중복 방지 상태이기 때문이다. subscriptions만 Actions cron도
    함께 읽는 공유 설정이라 Postgres ``notifications`` 스키마에 남는다.
    """
    constants = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in {"T_OUTBOX", "T_DELIVERIES"}:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
    assert constants["T_OUTBOX"] == "notification_outbox"
    assert constants["T_DELIVERIES"] == "notification_deliveries"
    tables = {m.group("table"): _columns_of_body(m.group("body")) for m in _SQLITE_TABLE_RE.finditer(sql)}
    insert_match = re.search(r"INSERT INTO \{T_OUTBOX\} \((?P<columns>[^)]+)\)", source)
    assert insert_match, "outbox.py enqueue()의 INSERT 컬럼 목록을 찾지 못했다"
    inserted = {column.strip() for column in insert_match.group("columns").split(",")}
    assert inserted <= tables[constants["T_OUTBOX"]]
    assert {"producer", "notification_key", "status", "failure_reason", "attempted_at"} <= tables[constants["T_DELIVERIES"]]


class NotificationGuardsTest(unittest.TestCase):
    def test_notification_boundary(self):
        sources = {
            p.relative_to(PACKAGE).as_posix(): p.read_text(encoding="utf-8")
            for p in PACKAGE.rglob("*.py")
            if "discord_admin" not in p.parts
        }
        self.assertGreaterEqual(len(sources), 8)
        assert_boundary(sources)

    def test_outbox_contract_matches_declared_sql(self):
        assert_schema_contract((PACKAGE / "outbox.py").read_text(encoding="utf-8"),
                               (ROOT / "db/sqlite/runtime/v1/40_notifications.sql").read_text(encoding="utf-8"))

    def assert_guard_fails(self, callback):
        result = unittest.TestResult()
        unittest.FunctionTestCase(callback).run(result)
        self.assertEqual(1, len(result.failures), result.errors)
        self.assertEqual([], result.errors)

    def test_individual_dependency_and_io_mutations_fail(self):
        cases = [
            ("service.py", "import requests"),
            ("service.py", "import investment_agent.execution.brokers.toss"),
            ("service.py", "from investment_agent.data.market import persistence"),
            ("service.py", "from investment_agent.trading import repository"),
            ("service.py", "from investment_agent.execution.approval import ledger"),
            ("service.py", "import yfinance"),
            ("service.py", "from ..data import market"),
            ("service.py", "db.table(SCHEMA, T_OUTBOX)"),
            ("service.py", "query.execute()"),
            ("renderers/reports.py", "from investment_agent.platform.db.postgres import Database"),
            ("renderers/reports.py", "from investment_agent.notifications.service import NotificationService"),
            ("outbox.py", "db.table('execution', 'orders')"),
            ("outbox.py", "db.table(SCHEMA, T_ORDERS)"),
            ("outbox.py", "query.delete()"),
            ("outbox.py", "db.rpc('anything')"),
            ("outbox.py", "db.schema('trading')"),
            ("outbox.py", "Database.from_config(config)"),
            ("service.py", "__import__('requests')"),
        ]
        for filename, source in cases:
            with self.subTest(filename=filename, source=source):
                self.assert_guard_fails(lambda: assert_boundary({filename: source}))

    def test_individual_schema_mutations_fail(self):
        source = (PACKAGE / "outbox.py").read_text(encoding="utf-8")
        sql = (ROOT / "db/sqlite/runtime/v1/40_notifications.sql").read_text(encoding="utf-8")
        for before, after in (
            ('T_OUTBOX = "notification_outbox"', 'T_OUTBOX = "orders"'),
            ('T_DELIVERIES = "notification_deliveries"', 'T_DELIVERIES = "fills"'),
            ('payload_json,status,attempt_count,claimed_at', 'payload_json,status,attempt_total,claimed_at'),
        ):
            with self.subTest(before=before):
                self.assertIn(before, source)
                self.assert_guard_fails(lambda: assert_schema_contract(source.replace(before, after), sql))
        self.assert_guard_fails(lambda: assert_schema_contract(source, sql.replace("failure_reason TEXT,", "wrong_reason TEXT,")))
