"""시세 기준 ETF를 SEC 투자회사 클래스 목록에서 등록하는 규칙."""
from __future__ import annotations

import unittest

from investment_agent.data.universe.infrastructure.sources.sec_entities import fetch_fund_listings

_FIELDS = ["cik", "seriesId", "classId", "symbol"]


def _source(rows):
    return lambda url: {"fields": _FIELDS, "data": rows}


class FundListingTest(unittest.TestCase):
    def test_only_requested_tickers_become_etf_listings(self) -> None:
        rows = fetch_fund_listings(["AGG"], get_json=_source([
            [1100663, "S000004362", "C000012092", "AGG"],
            [1100663, "S000004360", "C000012090", "TLT"],
        ]))
        self.assertEqual([("AGG", "0001100663", "etf")], [(r["ticker"], r["cik"], r["security_type"]) for r in rows])

    def test_a_ticker_on_two_share_classes_is_held(self) -> None:
        """어느 클래스인지 정하지 못하면 등록하지 않는다 — 다른 상품의 시세를 붙이지 않는다."""
        rows = fetch_fund_listings(["ABC"], get_json=_source([
            [1, "S1", "C1", "ABC"],
            [2, "S2", "C2", "ABC"],
        ]))
        self.assertEqual([], rows)

    def test_nothing_requested_reads_nothing(self) -> None:
        self.assertEqual([], fetch_fund_listings([], get_json=lambda url: self.fail("no request")))


if __name__ == "__main__":
    unittest.main()
