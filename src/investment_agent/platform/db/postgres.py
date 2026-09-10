"""Supabase(PostgREST) 접근의 유일한 자리.

## 조용히 틀리는 세 가지를 여기서 막는다

1. **응답 1,000행 상한.** PostgREST는 그 이상을 요구해도 예외를 던지지 않고 1,000행만
   준다. `select_paged()`를 거치지 않은 대량 조회는 "데이터가 원래 이만큼"처럼 보인다.
2. **정렬 없는 페이지네이션.** `ORDER BY` 없는 `LIMIT/OFFSET`은 요청 사이 행 순서가
   같다는 보장이 없어 페이지 경계로 행이 빠질 수 있다. 따라서 **두 번째 페이지가
   필요해지는 순간 예외를 던진다** — 한 페이지로 끝나는 조회는 그대로 쓰고, 위험한
   지점에서만 막힌다.
3. **긴 `in` 목록.** PostgREST는 값을 URL에 그대로 싣는다. 수백 개를 넣으면 URL 한도에
   걸리고, 이것은 행 상한과 **다른 벽**이라 페이지네이션으로는 풀리지 않는다.

## 연결은 객체로 전달한다

연결을 객체로 전달하면 테스트는 가짜 연결을 주입할 수 있고, 연결이 빠진 호출은 즉시
실패한다. 기존 함수형 저장소는 지연 연결 facade를 사용하며 두 진입점은 동일한
페이지 조회 계약을 공유한다.

## 스키마 client는 한 번만 만든다

supabase-py의 ``schema()``는 부를 때마다 PostgREST client를 새로 만들고, 그때마다
httpx client와 SSL context가 따라 생긴다 — 호출 하나가 0.4초다. 표를 열 때마다 그
값을 치르면 행마다 조회하는 경로가 네트워크가 아니라 CA 번들 로딩에서 느려진다.
그래서 스키마별 client를 프로세스 안에서 재사용한다.

## 도메인은 여기 없다

표 이름·컬럼·업서트 규칙은 각 도메인 repository가 안다. 이 파일은 "어떻게 읽고
쓰는가"만 안다.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable, Sequence
from functools import lru_cache
from typing import Any

from httpx import RemoteProtocolError
from supabase import Client, create_client

from investment_agent.config import Config
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

# PostgREST가 한 응답에 담는 최대 행 수. 넘기면 예외 없이 잘린다.
READ_PAGE_SIZE = 1000

# `in` 목록을 URL에 실을 때의 안전한 묶음 크기.
IN_FILTER_CHUNK = 100

# 한 번에 밀어 넣는 upsert 행 수. 너무 크면 PostgREST 쪽 statement_timeout(8초)에 걸린다.
WRITE_CHUNK = 500


@lru_cache(maxsize=1)
def service_client() -> Client:
    """service-role client를 실제 첫 호출 시 한 번 만든다."""
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


@lru_cache(maxsize=1)
def anon_client() -> Client:
    """공개 읽기용 anon client를 실제 첫 호출 시 한 번 만든다."""
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])


class SchemaClients:
    """스키마별 PostgREST client를 재사용하는 캐시.

    빌더는 호출마다 새로 만들어지지만 client 자체는 상태가 없다 — 헤더·타임아웃은
    만들 때 부모에서 복사되고 이후 바뀌지 않는다.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._by_schema: dict[str, Any] = {}

    def get(self, schema: str) -> Any:
        cached = self._by_schema.get(schema)
        if cached is None:
            cached = self._by_schema[schema] = self._client.schema(schema)
        return cached


class _LazyServiceClient:
    """모듈 import 시 연결하지 않는 service-role client facade."""

    def __init__(self) -> None:
        self._schemas: SchemaClients | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(service_client(), name)

    def schema(self, name: str) -> Any:
        if self._schemas is None:
            self._schemas = SchemaClients(service_client())
        return self._schemas.get(name)


sb = _LazyServiceClient()


class Database:
    """PostgREST 접근 객체. 진입점이 하나 만들어 필요한 곳에 넘긴다."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._schemas = SchemaClients(client)

    # ── 만들기 ────────────────────────────────────────────────────────────
    @classmethod
    def from_config(cls, config: Config) -> "Database":
        """service-role 키로 연결한다. 쓰기 권한이 있으므로 진입점에서만 만든다."""
        url, key = config.require("SUPABASE_URL", "SUPABASE_SERVICE_KEY")
        from supabase import create_client

        return cls(create_client(url, key))

    # ── 질의 만들기 ───────────────────────────────────────────────────────
    def table(self, schema: str, name: str) -> Any:
        """쿼리 빌더. 스키마를 반드시 함께 받는다 — 기본 스키마에 기대면 표를 옮길 때
        어느 스키마를 읽고 있었는지 코드만 봐서는 알 수 없다."""
        return self._schemas.get(schema).table(name)

    def rpc(self, schema: str, name: str, params: dict[str, Any] | None = None) -> Any:
        return self._schemas.get(schema).rpc(name, params or {})

    # ── 읽기 ──────────────────────────────────────────────────────────────
    def select_paged(
        self,
        builder_factory: Callable[[], Any],
        *,
        order_by: str | None = None,
        page_size: int = READ_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """1,000행 상한을 넘겨 끝까지 읽는다.

        `builder_factory`는 **호출마다 새 빌더**를 돌려줘야 한다. 빌더는 한 번 실행하면
        재사용할 수 없어서, 하나를 만들어 돌려쓰면 두 번째 페이지가 조용히 빈다.

        두 번째 페이지가 필요한데 `order_by`가 없으면 `ValueError`다. 자세한 이유는
        모듈 docstring 2번.
        """
        return select_all_paged(builder_factory, page_size=page_size, order_by=order_by)

    def select_in_chunks(
        self,
        *,
        schema: str,
        table: str,
        columns: str,
        filter_column: str,
        values: Sequence[Any],
        configure: Callable[[Any], Any] | None = None,
        order_by: str | None = None,
        chunk_size: int = IN_FILTER_CHUNK,
    ) -> list[dict[str, Any]]:
        """긴 `in` 목록을 URL 한도와 행 상한 없이 읽는다."""
        rows: list[dict[str, Any]] = []
        for chunk in chunk_values(values, chunk_size):
            def factory(subset: list[str] = chunk) -> Any:
                query = self.table(schema, table).select(columns).in_(filter_column, subset)
                return configure(query) if configure is not None else query

            rows.extend(self.select_paged(factory, order_by=order_by))
        return rows

    # ── 쓰기 ──────────────────────────────────────────────────────────────
    def upsert(
        self,
        *,
        schema: str,
        table: str,
        rows: Sequence[dict[str, Any]],
        on_conflict: str,
        chunk_size: int = WRITE_CHUNK,
    ) -> int:
        """충돌 키를 **명시적으로** 받아 나눠 넣는다.

        `on_conflict`를 생략할 수 있게 두지 않는 이유: 생략하면 PostgREST가 PK를
        추측하는데, 자연키가 따로 있는 표에서는 그 추측이 틀려 중복 행이 쌓인다.
        """
        if not rows:
            return 0
        written = 0
        for start in range(0, len(rows), chunk_size):
            batch = list(rows[start:start + chunk_size])
            self.table(schema, table).upsert(batch, on_conflict=on_conflict).execute()
            written += len(batch)
        return written

    def insert_ignore_duplicate(
        self,
        *,
        schema: str,
        table: str,
        row: dict[str, Any],
    ) -> bool:
        """넣는 데 성공하면 True, 이미 있으면 False.

        **선점(claim)에 쓴다.** "먼저 조회해서 없으면 넣기"는 두 러너가 동시에 조회하면
        둘 다 없다고 읽고 둘 다 넣는다. 넣기를 먼저 시도하고 unique 위반을 받는 쪽만
        경쟁을 이긴다.
        """
        from postgrest.exceptions import APIError

        try:
            self.table(schema, table).insert(row).execute()
            return True
        except APIError as exc:
            if str(exc.code or "") == "23505":  # unique_violation
                return False
            raise


def chunk_values(values: Iterable[Any], size: int = IN_FILTER_CHUNK) -> list[list[str]]:
    """`in` 목록을 **결정적으로** 나눈다(중복 제거 후 정렬).

    정렬하는 이유는 재현성이다. 묶음 경계가 호출마다 달라지면 실패를 재현할 수 없고,
    캐시도 매번 빗나간다.
    """
    ordered = sorted({str(value) for value in values if str(value or "").strip()})
    return [ordered[index:index + size] for index in range(0, len(ordered), size)]


def select_all_paged(
    builder_factory: Callable[[], Any],
    page_size: int = READ_PAGE_SIZE,
    order_by: str | None = None,
) -> list[dict[str, Any]]:
    """서버 행 상한과 정렬 계약을 검증하고 끝까지 읽는다."""
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= READ_PAGE_SIZE:
        raise ValueError(f"page_size must be an integer in [1, {READ_PAGE_SIZE}]")
    order_columns = [column.strip() for column in (order_by or "").split(",") if column.strip()]
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        # 연결 종료 시 이미 받은 행을 버리지 않고 같은 읽기 페이지만 재요청한다.
        for attempt in range(3):
            builder = builder_factory().range(start, start + page_size - 1)
            for column in order_columns:
                builder = builder.order(column)
            try:
                chunk = builder.execute().data or []
                break
            except RemoteProtocolError:
                if attempt == 2:
                    raise
                time.sleep(0.1 * (2 ** attempt))
        rows.extend(chunk)
        if len(chunk) < page_size:
            return rows
        if not order_columns:
            raise ValueError(
                "select_paged needs order_by once the result exceeds one page; "
                "unordered range reads can skip rows between pages"
            )
        start += page_size


def select_paged_in_chunks(
    builder_factory: Callable[[Sequence[str]], Any],
    values: Sequence[Any],
    *,
    order_by: str | None = None,
    chunk_size: int = IN_FILTER_CHUNK,
    paged_reader: Callable[..., list[dict[str, Any]]] = select_all_paged,
) -> list[dict[str, Any]]:
    """긴 membership 필터를 나눠 각 묶음을 안정적으로 페이지 조회한다."""
    rows: list[dict[str, Any]] = []
    for chunk in chunk_filter_values(values, chunk_size):
        rows.extend(
            paged_reader(
                lambda chunk=chunk: builder_factory(chunk),
                order_by=order_by,
            )
        )
    return rows


def chunk_filter_values(values: Sequence[Any], size: int = IN_FILTER_CHUNK) -> list[list[str]]:
    """긴 PostgREST `in` 목록을 결정적으로 나눈다."""
    return chunk_values(values, size)


def select_in_chunks(
    *,
    schema: str,
    table: str,
    select: str,
    filter_column: str,
    values: Sequence[Any],
    configure: Callable[[Any], Any] | None = None,
    order_by: str | None = None,
    chunk_size: int = IN_FILTER_CHUNK,
) -> list[dict[str, Any]]:
    """긴 `in` 목록을 나누고 각 묶음을 페이지네이션한다."""
    def builder(chunk: Sequence[str]) -> Any:
        query = sb.schema(schema).table(table).select(select).in_(filter_column, chunk)
        return configure(query) if configure is not None else query

    return select_paged_in_chunks(
        builder,
        values,
        order_by=order_by,
        chunk_size=chunk_size,
    )


__all__ = [
    "Database",
    "IN_FILTER_CHUNK",
    "READ_PAGE_SIZE",
    "WRITE_CHUNK",
    "anon_client",
    "chunk_values",
    "chunk_filter_values",
    "sb",
    "select_all_paged",
    "select_paged_in_chunks",
    "select_in_chunks",
    "service_client",
]
