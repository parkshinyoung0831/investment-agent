"""IC 표본의 종가 캐시는 날짜만이 아니라 종목까지 키로 삼는다(RS-16)."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.research.commands.factor_research import _CloseCache

DAY = date(2026, 9, 4)


class CloseCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        prices = {"AAA": 10.0, "BBB": 20.0, "NEW": 30.0}

        def closes_on(tickers, day):
            self.calls.append(tuple(tickers))
            return {ticker: prices[ticker] for ticker in tickers if ticker in prices}

        self.cache = _CloseCache(closes_on)

    def test_a_ticker_that_joins_later_still_gets_its_close_for_a_cached_day(self) -> None:
        """주간 표본에서 horizon 종료일은 몇 주 뒤 as_of의 시작일과 같다 — 그 사이 편입된 종목의 시작가가 있어야 한다."""
        self.cache(DAY, ["AAA", "BBB"])
        later = self.cache(DAY, ["AAA", "BBB", "NEW"])
        self.assertEqual(30.0, later["NEW"])

    def test_only_the_missing_tickers_are_fetched(self) -> None:
        self.cache(DAY, ["AAA", "BBB"])
        self.cache(DAY, ["AAA", "BBB", "NEW"])
        self.assertEqual([("AAA", "BBB"), ("NEW",)], self.calls)

    def test_a_repeated_request_reads_nothing(self) -> None:
        self.cache(DAY, ["AAA"])
        self.cache(DAY, ["AAA"])
        self.assertEqual([("AAA",)], self.calls)

    def test_a_ticker_without_a_close_is_not_asked_again_and_is_left_out(self) -> None:
        first = self.cache(DAY, ["AAA", "GONE"])
        second = self.cache(DAY, ["AAA", "GONE"])
        self.assertEqual({"AAA": 10.0}, first)
        self.assertEqual(first, second)
        self.assertEqual([("AAA", "GONE")], self.calls)


if __name__ == "__main__":
    unittest.main()
