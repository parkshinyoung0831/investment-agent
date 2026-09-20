"""오류 결과는 TTL 동안 캐시되지 않는다(DB-02)."""
from __future__ import annotations

import unittest

from investment_agent.platform.cache import cache_data
from investment_agent.reporting.models import DataResult


class CacheDoesNotHoldErrorsTest(unittest.TestCase):
    def test_error_is_retried_but_ok_is_cached(self) -> None:
        calls: list[int] = []
        outcomes = [
            DataResult.error(source="t", message="timeout"),
            DataResult.ok(rows=[{"a": 1}], source="t"),
        ]

        @cache_data(ttl="5m", max_entries=2)
        def load(key: str) -> DataResult:
            calls.append(1)
            return outcomes[min(len(calls) - 1, 1)]

        self.assertEqual(load("k").status, "error")
        self.assertEqual(load("k").status, "ok")     # 오류는 남지 않아 다시 조회했다
        self.assertEqual(load("k").status, "ok")     # 정상은 캐시에서 온다
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
