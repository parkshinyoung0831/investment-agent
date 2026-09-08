"""TradingRepository의 쿼리 계약을 로컬 SQLite 관계형 원장에 연결한다.

금융 데이터용 Database와 같은 작은 주입 계약을 쓰되 네트워크 클라이언트는 없다.
테이블·컬럼은 SQLite 선언에서 검증하며 값은 전부 바인딩한다.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace

from investment_agent.platform.db.sqlite import runtime_connection

TABLES = frozenset({"policies", "model_versions", "model_promotions", "decision_runs",
    "security_decisions", "decision_evidence", "signal_runs", "signals", "portfolio_proposals",
    "risk_decisions", "portfolio_decisions", "decision_evaluations", "attribution_reports"})
IMMUTABLE = frozenset({"policies", "model_versions", "signal_runs", "signals", "portfolio_proposals", "risk_decisions", "portfolio_decisions"})
SCHEMA_TRADING = "trading"
SCHEMA_REPORTING = "reporting"
V_CURRENT_MODEL_STAGE = "current_model_stage"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


def _name(value):
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError("invalid local ledger identifier")
    return '"' + value + '"'


class LocalTradingDatabase:
    """관계형 판단 원장의 원자 쓰기와 페이지 제한 없는 로컬 조회."""

    def __init__(self, path=None):
        self.path = path
        self._active = ContextVar(f"trading_connection_{id(self)}", default=None)

    @contextmanager
    def transaction(self, *, read_only=False):
        existing = self._active.get()
        if existing is not None:
            yield existing
            return
        with runtime_connection(self.path, read_only=read_only) as connection:
            token = self._active.set(connection)
            try:
                yield connection
            finally:
                self._active.reset(token)

    def table(self, schema, table):
        if schema == SCHEMA_REPORTING and table == V_CURRENT_MODEL_STAGE:
            return _Query(self, table)
        if schema != SCHEMA_TRADING or table not in TABLES:
            raise ValueError("unknown local trading table")
        return _Query(self, table)

    @staticmethod
    def columns(connection, table):
        return {row[1]: str(row[2]).upper() for row in connection.execute(f"PRAGMA table_info({_name(table)})")}

    @staticmethod
    def decode(row, columns):
        return {key: (json.loads(value) if value is not None and columns.get(key) == "JSON"
            else bool(value) if value is not None and columns.get(key) == "BOOLEAN" else value)
            for key, value in row.items()}

    def _write(self, connection, table, row, *, keys=(), ignore=False):
        columns = self.columns(connection, table)
        if set(row) - set(columns):
            raise ValueError(f"unknown {table} columns: {sorted(set(row) - set(columns))}")
        encoded = {key: json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) if value is not None and columns[key] == "JSON" else value for key, value in row.items()}
        if not keys:
            keys = tuple(item[1] for item in sorted(connection.execute(f"PRAGMA table_info({_name(table)})").fetchall(), key=lambda item: item[5]) if item[5])
        old = None
        if keys and all(key in row for key in keys):
            cursor = connection.execute(f"SELECT * FROM {_name(table)} WHERE " + " AND ".join(f"{_name(key)}=?" for key in keys), [encoded[key] for key in keys])
            result = cursor.fetchone()
            old = dict(zip([item[0] for item in cursor.description], result)) if result else None
        if old:
            if ignore:
                return 0
            if table in IMMUTABLE and any(old[key] != value for key, value in encoded.items()):
                raise ValueError(f"immutable {table} identity cannot be overwritten")
            changed = {key: value for key, value in encoded.items() if key not in keys}
            if changed:
                connection.execute(f"UPDATE {_name(table)} SET " + ','.join(f"{_name(key)}=?" for key in changed) + " WHERE " + ' AND '.join(f"{_name(key)}=?" for key in keys), [*changed.values(), *[encoded[key] for key in keys]])
        else:
            connection.execute(f"INSERT INTO {_name(table)} (" + ','.join(_name(key) for key in encoded) + ") VALUES (" + ','.join('?' for _ in encoded) + ")", list(encoded.values()))
        return 1

    def upsert(self, *, schema, table, rows, on_conflict):
        self.table(schema, table)
        with self.transaction() as connection:
            return sum(self._write(connection, table, dict(row), keys=tuple(on_conflict.split(','))) for row in rows)

    def insert_ignore_duplicate(self, *, schema, table, row):
        self.table(schema, table)
        with self.transaction() as connection:
            return self._write(connection, table, dict(row), ignore=True)

    def select_paged(self, factory, *, order_by, page_size=1000):
        query = factory()
        for column in order_by.split(','):
            query.order(column.strip())
        return query.execute().data

    def select_in_chunks(self, *, schema, table, columns, filter_column, values, order_by, configure=None, **kwargs):
        if not values:
            return []
        query = self.table(schema, table).select(columns).in_(filter_column, values)
        if configure:
            query = configure(query)
        return self.select_paged(lambda: query, order_by=order_by)

    def rpc(self, schema, name, params):
        if schema != SCHEMA_TRADING or name != "approve_model_promotion":
            raise ValueError("unknown local trading command")
        def run():
            with self.transaction():
                current = self.table(SCHEMA_REPORTING, V_CURRENT_MODEL_STAGE).select("stage").eq("artifact_id", params["p_artifact_id"]).execute().data
                if not current or current[0]["stage"] != params["p_from_stage"]:
                    raise ValueError("model promotion stage changed")
                row = {"artifact_id": params["p_artifact_id"], "from_stage": params["p_from_stage"], "to_stage": params["p_to_stage"], "status": "approved", "evidence": params["p_evidence"], "approved_by": params["p_approved_by"], "approved_at": params["p_approved_at"], "confirmation_text": params["p_confirmation_text"]}
                return self.table(SCHEMA_TRADING, "model_promotions").insert(row).execute()
        return SimpleNamespace(execute=run)


class _Query:
    def __init__(self, database, table):
        self.database, self.name = database, table
        self.projection, self.predicates, self.params, self.ordering = "*", [], [], []
        self.maximum, self.offset, self.write, self.payload = None, 0, None, None

    def select(self, columns):
        self.projection = columns
        return self

    def _filter(self, column, op, value):
        self.predicates.append(f"{_name(column)} {op} ?")
        self.params.append(value)
        return self

    def eq(self, column, value): return self._filter(column, "=", value)
    def gt(self, column, value): return self._filter(column, ">", value)
    def gte(self, column, value): return self._filter(column, ">=", value)
    def lt(self, column, value): return self._filter(column, "<", value)
    def lte(self, column, value): return self._filter(column, "<=", value)

    def in_(self, column, values):
        values = list(values)
        self.predicates.append(f"{_name(column)} IN (" + ','.join('?' for _ in values) + ")")
        self.params.extend(values)
        return self

    def order(self, column, *, desc=False):
        self.ordering.append(_name(column) + (" DESC" if desc else " ASC"))
        return self

    def limit(self, value):
        self.maximum = max(0, int(value))
        return self

    def insert(self, payload):
        self.write, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.write, self.payload = "update", payload
        return self

    def execute(self):
        # 기본 생성은 writer 명령에서만 한다. 읽기 전용 화면은 DB를 만들지 않는다.
        with self.database.transaction(read_only=self.write is None) as connection:
            table = self.name
            if table == "current_model_stage":
                source = "(SELECT m.*, coalesce((SELECT p.to_stage FROM model_promotions p WHERE p.artifact_id=m.artifact_id AND p.status='approved' ORDER BY p.approved_at DESC,p.promotion_id DESC LIMIT 1),'shadow') AS stage FROM model_versions m)"
                columns = {**self.database.columns(connection, "model_versions"), "stage": "TEXT"}
            else:
                source = _name(table)
                columns = self.database.columns(connection, table)
            where = " WHERE " + ' AND '.join(self.predicates) if self.predicates else ""
            if self.write == "insert":
                self.database._write(connection, table, self.payload)
                cursor = connection.execute(f"SELECT * FROM {source} WHERE rowid=last_insert_rowid()")
            elif self.write == "update":
                if set(self.payload) - set(columns):
                    raise ValueError("unknown local update column")
                values = [json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) if value is not None and columns[key] == "JSON" else value for key, value in self.payload.items()]
                cursor = connection.execute(f"UPDATE {source} SET " + ','.join(f"{_name(key)}=?" for key in self.payload) + where + " RETURNING *", [*values, *self.params])
            else:
                ordering = " ORDER BY " + ','.join(self.ordering) if self.ordering else ""
                limit = f" LIMIT {self.maximum}" if self.maximum is not None else ""
                cursor = connection.execute(f"SELECT * FROM {source}" + where + ordering + limit, self.params)
            names = [item[0] for item in cursor.description]
            rows = [self.database.decode(dict(zip(names, row)), columns) for row in cursor.fetchall()]
            if self.projection != "*":
                fields = [part.strip() for part in self.projection.split(',')]
                result = []
                for row in rows:
                    projected = {}
                    for field in fields:
                        if field == "risk_decisions(approved_weights)":
                            risk = self.database.table(SCHEMA_TRADING, "risk_decisions").select("approved_weights").eq("risk_decision_id", row["risk_decision_id"]).execute().data
                            projected["risk_decisions"] = risk[0] if risk else None
                        elif field in row:
                            projected[field] = row[field]
                        else:
                            raise ValueError(f"unknown local projection: {field}")
                    result.append(projected)
                rows = result
            return SimpleNamespace(data=rows)
