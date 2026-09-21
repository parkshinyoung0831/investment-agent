"""스키마 client를 표 하나 열 때마다 새로 만들지 않는다.

supabase-py의 ``schema()``는 부를 때마다 PostgREST client를 새로 만들고, 그때마다
httpx client와 SSL context가 따라 생긴다 — 실측 0.4초다. 행마다 조회하는 경로가
있으면 그 비용이 곱해지고, 그것은 예외 없이 **그냥 느려지는** 방식으로만 드러난다
(econ 백필이 30분 동안 CPU만 태우며 첫 표에서 멈춰 있었다).
"""
from __future__ import annotations

import unittest
from typing import Any

from investment_agent.platform.db.postgres import Database, SchemaClients


class _Schema:
    def __init__(self, name: str) -> None:
        self.name = name

    def table(self, name: str) -> str:
        return f"{self.name}.{name}"

    def rpc(self, name: str, params: dict[str, Any]) -> str:
        return f"{self.name}.{name}()"


class _Client:
    def __init__(self) -> None:
        self.schema_calls: list[str] = []

    def schema(self, name: str) -> _Schema:
        self.schema_calls.append(name)
        return _Schema(name)


class SchemaClientReuseTest(unittest.TestCase):
    def test_the_same_schema_is_built_once(self) -> None:
        client = _Client()
        cache = SchemaClients(client)
        for _ in range(5):
            cache.get("macro")
        self.assertEqual(["macro"], client.schema_calls)

    def test_different_schemas_stay_separate(self) -> None:
        client = _Client()
        cache = SchemaClients(client)
        self.assertEqual("macro.series", cache.get("macro").table("series"))
        self.assertEqual("universe.securities", cache.get("universe").table("securities"))
        self.assertEqual(["macro", "universe"], client.schema_calls)

    def test_database_reuses_the_schema_across_tables_and_rpc(self) -> None:
        client = _Client()
        database = Database(client)
        database.table("macro", "series")
        database.table("macro", "measures")
        database.rpc("macro", "some_function")
        self.assertEqual(["macro"], client.schema_calls)


class Http1SessionTest(unittest.TestCase):
    """스키마 client의 HTTP 세션은 HTTP/1.1이다 — HTTP/2 연결은 스레드가 함께 쓰면 깨진다."""

    @staticmethod
    def _uses_http2(client: Any) -> bool:
        return bool(client.session._transport._pool._http2)

    def test_schema_clients_use_a_thread_safe_http1_pool(self) -> None:
        from postgrest import SyncPostgrestClient

        parent = SyncPostgrestClient("https://example.supabase.co/rest/v1", headers={"apikey": "k"})
        self.assertTrue(self._uses_http2(parent))  # 라이브러리 기본. 이것이 바뀌면 이 시험을 다시 본다
        child = SchemaClients(parent).get("fundamentals")
        self.assertFalse(self._uses_http2(child))
        self.assertEqual(str(child.session.base_url), "https://example.supabase.co/rest/v1/")
        self.assertEqual(child.session.headers["apikey"], "k")

    def test_swapping_twice_or_concurrently_never_closes_the_live_session(self) -> None:
        """같은 client를 두 번 넘겨도 두 번째가 첫 번째의 새 세션을 닫으면 안 된다(재적재 중 실제로 났다)."""
        from concurrent.futures import ThreadPoolExecutor

        from postgrest import SyncPostgrestClient

        from investment_agent.platform.db.postgres import use_http1_session

        client = SyncPostgrestClient("https://example.supabase.co/rest/v1", headers={})
        with ThreadPoolExecutor(8) as executor:
            list(executor.map(lambda _: use_http1_session(client), range(16)))
        self.assertFalse(client.session.is_closed)
        live = client.session
        use_http1_session(client)
        self.assertIs(client.session, live)

    def test_a_client_without_an_httpx_session_is_left_alone(self) -> None:
        from investment_agent.platform.db.postgres import use_http1_session

        stub = _Schema("x")
        self.assertIs(use_http1_session(stub), stub)


if __name__ == "__main__":
    unittest.main()
