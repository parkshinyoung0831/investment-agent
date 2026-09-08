"""조용히 잘리거나 빠지는 읽기를 막는지 본다."""
from __future__ import annotations

import unittest
from typing import Any

from investment_agent.platform.db.postgres import (
    IN_FILTER_CHUNK,
    READ_PAGE_SIZE,
    Database,
    chunk_values,
    select_all_paged,
    select_paged_in_chunks,
)


class _Result:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _FakeBuilder:
    """PostgREST 빌더 체인 흉내. 실제로 호출된 range/order/in_을 기록한다."""

    def __init__(self, table: "_FakeTable") -> None:
        self._table = table
        self._start = 0
        self._stop = READ_PAGE_SIZE - 1
        self._orders: list[str] = []
        self._in_values: list[str] | None = None

    def select(self, _columns: str) -> "_FakeBuilder":
        return self

    def in_(self, _column: str, values: list[str]) -> "_FakeBuilder":
        self._in_values = list(values)
        return self

    def eq(self, _column: str, _value: Any) -> "_FakeBuilder":
        return self

    def range(self, start: int, stop: int) -> "_FakeBuilder":
        self._start, self._stop = start, stop
        return self

    def order(self, column: str) -> "_FakeBuilder":
        self._orders.append(column)
        return self

    def upsert(self, rows: list[dict], *, on_conflict: str) -> "_FakeBuilder":
        self._table.upserts.append((list(rows), on_conflict))
        return self

    def insert(self, row: dict) -> "_FakeBuilder":
        self._table.inserts.append(dict(row))
        if self._table.raise_on_insert is not None:
            raise self._table.raise_on_insert
        return self

    def execute(self) -> _Result:
        source = self._table.rows
        if self._in_values is not None:
            self._table.in_calls.append(list(self._in_values))
            source = [row for row in source if str(row.get("ticker")) in set(self._in_values)]
        self._table.orders.append(list(self._orders))
        return _Result(source[self._start:self._stop + 1])


class _FakeTable:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.orders: list[list[str]] = []
        self.in_calls: list[list[str]] = []
        self.upserts: list[tuple[list[dict], str]] = []
        self.inserts: list[dict] = []
        self.raise_on_insert: BaseException | None = None

    def builder(self) -> _FakeBuilder:
        return _FakeBuilder(self)


class _FakeClient:
    def __init__(self, table: _FakeTable) -> None:
        self._table = table
        self.schemas: list[str] = []

    def schema(self, name: str) -> "_FakeClient":
        self.schemas.append(name)
        return self

    def table(self, _name: str) -> _FakeBuilder:
        return self._table.builder()


def _db(rows: list[dict]) -> tuple[Database, _FakeTable]:
    table = _FakeTable(rows)
    return Database(_FakeClient(table)), table


class SelectPagedTest(unittest.TestCase):
    def test_both_entrypoints_reject_server_truncating_page_sizes_before_query(self):
        db, table = _db([])
        for reader in (db.select_paged, select_all_paged):
            for size in (0, -1, 1001, 2000, True, 1.5):
                with self.subTest(reader=reader, size=size), self.assertRaises(ValueError):
                    reader(table.builder, page_size=size, order_by="ticker")
        self.assertEqual([], table.orders)

    def test_facade_requires_order_at_a_full_page(self):
        _, table = _db([{"ticker": str(i)} for i in range(1000)])
        with self.assertRaisesRegex(ValueError, "order_by"):
            select_all_paged(table.builder)

    def test_facade_reads_all_pages_in_stable_order(self):
        rows = [{"ticker": str(i)} for i in range(2011)]
        _, table = _db(rows)
        self.assertEqual(rows, select_all_paged(table.builder, order_by="ticker"))
        self.assertEqual([["ticker"]] * 3, table.orders)

    def test_single_page_needs_no_order(self) -> None:
        db, _ = _db([{"ticker": "A"}])
        self.assertEqual(1, len(db.select_paged(lambda: db.table("market", "t").select("*"))))

    def test_reads_past_the_thousand_row_cap(self) -> None:
        rows = [{"ticker": f"T{i:05d}"} for i in range(READ_PAGE_SIZE + 7)]
        db, _ = _db(rows)
        got = db.select_paged(lambda: db.table("market", "t").select("*"), order_by="ticker")
        self.assertEqual(len(rows), len(got))

    def test_second_page_without_order_by_raises(self) -> None:
        """정렬 없는 range 읽기는 페이지 경계로 행이 빠질 수 있다. 조용히 두지 않는다."""
        db, _ = _db([{"ticker": f"T{i:05d}"} for i in range(READ_PAGE_SIZE + 1)])
        with self.assertRaises(ValueError) as ctx:
            db.select_paged(lambda: db.table("market", "t").select("*"))
        self.assertIn("order_by", str(ctx.exception))

    def test_order_columns_are_applied_to_every_page(self) -> None:
        db, table = _db([{"ticker": f"T{i:05d}"} for i in range(READ_PAGE_SIZE + 1)])
        db.select_paged(lambda: db.table("market", "t").select("*"), order_by="ticker, trade_date")
        self.assertTrue(table.orders)
        for applied in table.orders:
            self.assertEqual(["ticker", "trade_date"], applied)


class SelectInChunksTest(unittest.TestCase):
    def test_long_in_list_is_split(self) -> None:
        values = [f"T{i:04d}" for i in range(250)]
        db, table = _db([{"ticker": value} for value in values])
        got = db.select_in_chunks(
            schema="market", table="t", columns="ticker",
            filter_column="ticker", values=values, order_by="ticker",
        )
        self.assertEqual(250, len(got))
        self.assertEqual(3, len(table.in_calls))
        self.assertTrue(all(len(call) <= IN_FILTER_CHUNK for call in table.in_calls))


class SelectPagedInChunksTest(unittest.TestCase):
    def test_builder_factory_receives_stable_chunks_and_paged_reader(self) -> None:
        values = [f"T{i:04d}" for i in range(IN_FILTER_CHUNK + 2)]
        db, table = _db([{"ticker": value} for value in values])

        got = select_paged_in_chunks(
            lambda chunk: db.table("market", "t").select("ticker").in_("ticker", chunk),
            list(reversed(values)),
            order_by="ticker",
            paged_reader=db.select_paged,
        )

        self.assertEqual(values, [row["ticker"] for row in got])
        self.assertEqual(2, len(table.in_calls))
        self.assertTrue(all(len(chunk) <= IN_FILTER_CHUNK for chunk in table.in_calls))


class ChunkValuesTest(unittest.TestCase):
    def test_duplicates_removed_and_order_is_deterministic(self) -> None:
        self.assertEqual([["A", "B"]], chunk_values(["B", "A", "B"], 10))
        self.assertEqual(chunk_values(["c", "a", "b"], 2), chunk_values(["b", "c", "a"], 2))

    def test_blank_values_are_dropped(self) -> None:
        self.assertEqual([["A"]], chunk_values(["A", "", "   ", None], 10))


class WriteTest(unittest.TestCase):
    def test_upsert_splits_into_chunks_and_keeps_conflict_key(self) -> None:
        db, table = _db([])
        rows = [{"ticker": f"T{i}"} for i in range(12)]
        self.assertEqual(12, db.upsert(schema="market", table="t", rows=rows,
                                       on_conflict="ticker", chunk_size=5))
        self.assertEqual([5, 5, 2], [len(batch) for batch, _ in table.upserts])
        self.assertTrue(all(key == "ticker" for _, key in table.upserts))

    def test_empty_upsert_touches_nothing(self) -> None:
        db, table = _db([])
        self.assertEqual(0, db.upsert(schema="market", table="t", rows=[], on_conflict="ticker"))
        self.assertEqual([], table.upserts)

    def test_claim_returns_false_on_unique_violation(self) -> None:
        from postgrest.exceptions import APIError

        db, table = _db([])
        table.raise_on_insert = APIError({"code": "23505", "message": "duplicate key"})
        self.assertFalse(db.insert_ignore_duplicate(schema="notifications", table="outbox", row={"k": "1"}))

    def test_claim_reraises_other_errors(self) -> None:
        """권한·제약 오류를 '이미 있음'으로 삼키면 알림이 조용히 사라진다."""
        from postgrest.exceptions import APIError

        db, table = _db([])
        table.raise_on_insert = APIError({"code": "42501", "message": "permission denied"})
        with self.assertRaises(APIError):
            db.insert_ignore_duplicate(schema="notifications", table="outbox", row={"k": "1"})

    def test_claim_returns_true_when_inserted(self) -> None:
        db, table = _db([])
        self.assertTrue(db.insert_ignore_duplicate(schema="notifications", table="outbox", row={"k": "1"}))
        self.assertEqual([{"k": "1"}], table.inserts)


if __name__ == "__main__":
    unittest.main()
