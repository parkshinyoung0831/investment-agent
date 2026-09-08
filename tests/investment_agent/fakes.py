"""테스트가 쓰는 가짜 PostgREST.

## 왜 patch가 아니라 가짜 객체인가

`Database`를 인자로 받는 구조에서는 가짜 연결을 직접 주입한다. 연결을 주입하지
않으면 즉시 실패하므로 테스트가 실제 DB에 접근하는 경로가 없다.

여기 구현하는 것은 실제로 쓰는 연산뿐이다. 완전한 PostgREST 흉내를 목표로 하면
가짜 자체가 검증이 필요한 물건이 된다.
"""
from __future__ import annotations

from typing import Any, Callable

from investment_agent.platform.db.postgres import Database


class _Result:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class FakeQuery:
    """`sb.schema(s).table(t)`가 돌려주는 빌더 흉내."""

    def __init__(self, store: "FakeDatabase", schema: str, table: str) -> None:
        self._store = store
        self._table_key = (schema, table)
        self._filters: list[Callable[[dict[str, Any]], bool]] = []
        self._order: list[tuple[str, bool]] = []
        self._range: tuple[int, int] | None = None
        self._limit: int | None = None
        self._negate_next = False
        self._eq_terms: dict[str, Any] = {}

    # ── 선택 ──────────────────────────────────────────────────────────────
    def select(self, columns: str = "*") -> "FakeQuery":
        self._columns = columns
        return self

    # ── 필터 ──────────────────────────────────────────────────────────────
    # PostgREST 필터는 URL 문자열로 간다. `in_("security_id", ["1"])`이 bigint 컬럼에
    # 맞는 것은 서버가 형을 맞춰 주기 때문이다. 가짜가 파이썬 값으로 엄격히 비교하면
    # **실제로는 되는 조회가 테스트에서만 빈 결과**가 되어, 없는 버그를 쫓게 된다.
    @staticmethod
    def _key(value: Any) -> Any:
        return None if value is None else str(value)

    def eq(self, column: str, value: Any) -> "FakeQuery":
        wanted = self._key(value)
        # UPDATE/DELETE가 **무엇을 골랐는지**도 기록해야 한다. 값만 보면 "한 행을
        # 고쳤다"와 "표 전체를 고쳤다"가 같은 얼굴이다.
        self._eq_terms[column] = value
        return self._add(lambda row: self._key(row.get(column)) == wanted)

    def neq(self, column: str, value: Any) -> "FakeQuery":
        wanted = self._key(value)
        return self._add(lambda row: self._key(row.get(column)) != wanted)

    def lt(self, column: str, value: Any) -> "FakeQuery":
        return self._add(lambda row: row.get(column) is not None and str(row[column]) < str(value))

    def lte(self, column: str, value: Any) -> "FakeQuery":
        return self._add(lambda row: row.get(column) is not None and str(row[column]) <= str(value))

    def gte(self, column: str, value: Any) -> "FakeQuery":
        return self._add(lambda row: row.get(column) is not None and str(row[column]) >= str(value))

    def gt(self, column: str, value: Any) -> "FakeQuery":
        return self._add(lambda row: row.get(column) is not None and str(row[column]) > str(value))

    def in_(self, column: str, values: list[Any]) -> "FakeQuery":
        wanted = {self._key(value) for value in values}
        self._store.in_calls.append((self._table_key, column, list(values)))
        return self._add(lambda row: self._key(row.get(column)) in wanted)

    def is_(self, column: str, value: str) -> "FakeQuery":
        if value != "null":
            raise NotImplementedError(f"is_({value!r}) is not modelled")
        return self._add(lambda row: row.get(column) is None)

    @property
    def not_(self) -> "FakeQuery":
        self._negate_next = True
        return self

    def _add(self, predicate: Callable[[dict[str, Any]], bool]) -> "FakeQuery":
        if self._negate_next:
            self._negate_next = False
            self._filters.append(lambda row: not predicate(row))
        else:
            self._filters.append(predicate)
        return self

    # ── 정렬·범위 ─────────────────────────────────────────────────────────
    def order(self, column: str, desc: bool = False) -> "FakeQuery":
        self._order.append((column, desc))
        return self

    def limit(self, count: int) -> "FakeQuery":
        self._limit = count
        return self

    def range(self, start: int, stop: int) -> "FakeQuery":
        self._range = (start, stop)
        return self

    # ── 쓰기 ──────────────────────────────────────────────────────────────
    def upsert(self, rows: list[dict[str, Any]], *, on_conflict: str) -> "FakeQuery":
        self._store.upserts.append((self._table_key, list(rows), on_conflict))
        return self

    def insert(self, row: dict[str, Any] | list[dict[str, Any]]) -> "FakeQuery":
        payload = [dict(item) for item in row] if isinstance(row, list) else dict(row)
        self._store.inserts.append((self._table_key, payload))
        error = self._store.insert_error
        if error is not None:
            raise error
        return self

    def update(self, values: dict[str, Any]) -> "FakeQuery":
        self._store.updates.append((self._table_key, dict(values)))
        # `.update(...)`가 `.eq(...)`보다 먼저 불린다 — 살아 있는 dict를 넣어
        # 뒤따르는 필터가 같은 자리에 채워지게 한다.
        self._store.update_filters.append((self._table_key, self._eq_terms))
        return self

    # ── 실행 ──────────────────────────────────────────────────────────────
    def execute(self) -> _Result:
        rows = [dict(row) for row in self._store.tables.get(self._table_key, [])]
        for predicate in self._filters:
            rows = [row for row in rows if predicate(row)]
        for column, desc in reversed(self._order):
            rows.sort(key=lambda row: (row.get(column) is None, row.get(column)), reverse=desc)
        if self._range is not None:
            start, stop = self._range
            rows = rows[start:stop + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        self._store.executed.append(self._table_key)
        return _Result(rows)


class FakeRpc:
    """`sb.schema(s).rpc(name, params)`가 돌려주는 호출 흉내."""

    def __init__(self, store: "FakeDatabase", schema: str, name: str, params: dict[str, Any]) -> None:
        self._store = store
        self.schema_name = schema
        self.name = name
        self.params = dict(params)

    def execute(self) -> _Result:
        self._store.rpc_calls.append((self.schema_name, self.name, dict(self.params)))
        return _Result(self._store.rpc_result)


class FakeClient:
    def __init__(self, store: "FakeDatabase") -> None:
        self._store = store
        self._schema = ""

    def schema(self, name: str) -> "FakeClient":
        clone = FakeClient(self._store)
        clone._schema = name
        return clone

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self._store, self._schema, name)

    def rpc(self, name: str, params: dict[str, Any] | None = None) -> FakeRpc:
        return FakeRpc(self._store, self._schema, name, params or {})


class FakeDatabase(Database):
    """메모리 표를 가진 `Database`. 테스트는 이것을 저장소에 그대로 넣는다."""

    def __init__(self, tables: dict[tuple[str, str], list[dict[str, Any]]] | None = None) -> None:
        self.tables = dict(tables or {})
        self.upserts: list[tuple[tuple[str, str], list[dict[str, Any]], str]] = []
        self.inserts: list[tuple[tuple[str, str], dict[str, Any]]] = []
        self.updates: list[tuple[tuple[str, str], dict[str, Any]]] = []
        #: UPDATE가 고른 eq 조건. `updates`와 같은 순서다.
        self.update_filters: list[tuple[tuple[str, str], dict[str, Any]]] = []
        self.in_calls: list[tuple[tuple[str, str], str, list[Any]]] = []
        self.executed: list[tuple[str, str]] = []
        self.insert_error: BaseException | None = None
        self.rpc_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.rpc_result: Any = 1
        super().__init__(FakeClient(self))

    def put(self, schema: str, table: str, rows: list[dict[str, Any]]) -> None:
        self.tables[(schema, table)] = [dict(row) for row in rows]


__all__ = ["FakeClient", "FakeDatabase", "FakeQuery", "FakeRpc"]
