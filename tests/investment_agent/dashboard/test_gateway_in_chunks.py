"""대시보드 게이트웨이도 `in` 목록의 URL 한도를 지킨다.

PostgREST는 `in` 값을 URL에 그대로 싣는다. 행 상한과 **다른 벽**이라 페이지네이션
으로는 풀리지 않고, 넘기면 400이 온다. 실적 화면이 그랬다 — 관심종목 전체의 공시
번호 2,000여 개를 한 요청에 담아 "실적 DB 조회에 실패했습니다"만 남겼다.

`platform.db.postgres`는 이미 `select_in_chunks`로 이 벽을 다루는데, 읽기 전용
게이트웨이만 그것을 몰랐다.
"""
from __future__ import annotations

import unittest
from typing import Any

from investment_agent.dashboard.db import SelectOnlyGateway
from investment_agent.platform.db.postgres import IN_FILTER_CHUNK


class _Query:
    def __init__(self, calls: list[dict], rows: list[dict]) -> None:
        self._calls = calls
        self._rows = rows
        self._in: dict[str, list] = {}

    def select(self, *_a, **_k) -> "_Query":
        return self

    def eq(self, *_a, **_k) -> "_Query":
        return self

    def in_(self, column: str, values: list) -> "_Query":
        self._in[column] = list(values)
        return self

    def order(self, *_a, **_k) -> "_Query":
        return self

    def limit(self, *_a, **_k) -> "_Query":
        return self

    def range(self, *_a, **_k) -> "_Query":
        return self

    def execute(self) -> Any:
        self._calls.append(dict(self._in))
        wanted = set(self._in.get("accession_no", []))
        return type("R", (), {"data": [r for r in self._rows if r["accession_no"] in wanted]})()


class _Client:
    def __init__(self, rows: list[dict]) -> None:
        self.calls: list[dict] = []
        self._rows = rows

    def schema(self, _name: str) -> "_Client":
        return self

    def table(self, _name: str) -> _Query:
        return _Query(self.calls, self._rows)


class GatewayInChunkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.accessions = [f"{n:010d}-25-000001" for n in range(250)]
        self.rows = [{"accession_no": value} for value in self.accessions]
        self.client = _Client(self.rows)
        self.gateway = SelectOnlyGateway(self.client)

    def _read(self, values: list[str]) -> list[dict]:
        return self.gateway.select_rows(
            schema="fundamentals", table="filings", columns="accession_no",
            in_values={"accession_no": values},
        )

    def test_a_long_list_is_split_below_the_url_limit(self) -> None:
        self._read(self.accessions)
        self.assertGreater(len(self.client.calls), 1)
        for call in self.client.calls:
            self.assertLessEqual(len(call["accession_no"]), IN_FILTER_CHUNK)

    def test_every_row_comes_back_exactly_once(self) -> None:
        rows = self._read(self.accessions)
        found = [row["accession_no"] for row in rows]
        self.assertEqual(len(self.accessions), len(found))
        self.assertEqual(set(self.accessions), set(found))

    def test_a_short_list_still_takes_one_request(self) -> None:
        self._read(self.accessions[:10])
        self.assertEqual(1, len(self.client.calls))

    def test_an_empty_membership_filter_reads_nothing(self) -> None:
        self.assertEqual([], self._read([]))
        self.assertEqual([], self.client.calls)


if __name__ == "__main__":
    unittest.main()
