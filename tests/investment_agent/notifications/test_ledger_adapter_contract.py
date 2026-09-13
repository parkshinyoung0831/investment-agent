"""Supabase 원장 어댑터가 선언 SQL과 같은 이름을 부르는지 본다.

RPC 인자 이름이 하나라도 어긋나면 PostgREST는 "함수를 찾지 못했다"는 404만 준다 —
테스트는 네트워크를 때리지 않으므로 이름을 선언 SQL과 직접 맞춘다.
"""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from investment_agent.notifications import db as ledger_db
from tests.investment_agent.test_schema_alignment import _columns_of_body

ROOT = Path(__file__).resolve().parents[3]
SQL = (ROOT / "db/postgres/v1/60_notifications.sql").read_text(encoding="utf-8")
_FUNCTION = re.compile(
    r"CREATE OR REPLACE FUNCTION (?P<schema>\w+)\.(?P<name>\w+)\((?P<params>.*?)\)\s*RETURNS",
    re.DOTALL,
)
_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS (?P<schema>\w+)\.(?P<table>\w+) \((?P<body>.*?)\n\);", re.DOTALL)


def declared_functions() -> dict[str, list[str]]:
    functions = {}
    for match in _FUNCTION.finditer(SQL):
        params = [line.strip().split()[0] for line in match.group("params").split(",") if line.strip()]
        functions[match.group("name")] = params
    return functions


def declared_columns() -> dict[str, set[str]]:
    return {match.group("table"): _columns_of_body(match.group("body")) for match in _TABLE.finditer(SQL)}


class _Query:
    def __init__(self, recorder: "_Database", table: str) -> None:
        self.recorder, self.table = recorder, table
        self.not_ = self

    def select(self, columns: str):
        self.recorder.columns.setdefault(self.table, set()).update(c.strip() for c in columns.split(","))
        return self

    def eq(self, column: str, _value: Any):
        self.recorder.columns.setdefault(self.table, set()).add(column)
        return self

    def is_(self, column: str, _value: Any):
        return self.eq(column, _value)

    def in_(self, column: str, _values: Any):
        return self.eq(column, _values)

    def order(self, column: str, desc: bool = False):
        return self.eq(column, desc)

    def limit(self, _n: int):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class _Database:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.columns: dict[str, set[str]] = {}
        self.inserted: list[tuple[str, dict]] = []
        self.upserted: list[tuple[str, list, str]] = []

    def rpc(self, schema: str, name: str, params: dict):
        self.calls.append((schema, name, params))
        data: Any = [] if name == ledger_db.RPC_RESERVE else 1
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=data))

    def table(self, schema: str, name: str):
        assert schema == ledger_db.SCHEMA
        return _Query(self, name)

    def insert_ignore_duplicate(self, *, schema: str, table: str, row: dict) -> bool:
        self.inserted.append((table, row))
        return True

    def upsert(self, *, schema: str, table: str, rows: list, on_conflict: str) -> int:
        self.upserted.append((table, rows, on_conflict))
        return len(rows)


class LedgerAdapterContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.database = _Database()
        self.ledger = ledger_db.PostgresNotificationLedger(self.database)

    def test_every_rpc_is_called_with_exactly_the_declared_parameters(self) -> None:
        keys = [("A", "1")]
        self.ledger.reserve("t.x", [{"subject": "A"}], owner="o", lease_seconds=60, revisable=True)
        self.ledger.begin_send("t.x", keys, owner="o")
        self.ledger.finish("t.x", keys, owner="o", action="create", outcome="sent",
                           location_id="1", message_id="2", failure_code=None, retry_seconds=None)
        self.ledger.replay("t.x", "A", "1")

        functions = declared_functions()
        self.assertEqual({name for _, name, _ in self.database.calls}, set(functions))
        for schema, name, params in self.database.calls:
            with self.subTest(function=name):
                self.assertEqual(schema, "notifications")
                self.assertEqual(list(params), functions[name])

    def test_table_reads_and_writes_use_declared_columns(self) -> None:
        self.ledger.last_known("t.x", "A")
        self.ledger.thread("1", "AVGO")
        self.ledger.ensure_baseline("t.x", datetime(2026, 9, 13, tzinfo=timezone.utc))
        self.ledger.remember_thread("1", "AVGO", "2")

        columns = declared_columns()
        for table, used in self.database.columns.items():
            with self.subTest(table=table):
                self.assertLessEqual(used, columns[table])
        for table, row in self.database.inserted:
            self.assertLessEqual(set(row), columns[table])
        for table, rows, on_conflict in self.database.upserted:
            self.assertLessEqual(set(rows[0]) | set(on_conflict.split(",")), columns[table])

    def test_the_parser_sees_the_real_declaration(self) -> None:
        """파서가 아무것도 못 찾으면 위 두 검사는 공허하게 통과한다."""
        self.assertEqual(set(declared_functions()), {"reserve", "begin_send", "finish", "replay"})
        self.assertIn("sent_revision", declared_columns()["notices"])
        self.assertIn("status", declared_columns()["notices"])
        self.assertNotIn("CONSTRAINT", declared_columns()["notices"])
        self.assertIn("thread_id", declared_columns()["threads"])


if __name__ == "__main__":
    unittest.main()
