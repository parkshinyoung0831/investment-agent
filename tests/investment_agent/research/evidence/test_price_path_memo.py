"""사후 평가가 같은 기준 종목 경로를 케이스마다 다시 읽지 않는다(PB-3)."""
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from investment_agent.research.evidence import reader as reader_module
from investment_agent.research.evidence.reader import PitReader


def _rows(ticker: str) -> list[dict]:
    return [{"ticker": ticker, "trade_date": f"2026-09-0{day}", "close": 100.0 + day} for day in range(1, 4)]


class PricePathMemoTest(unittest.TestCase):
    def test_same_ticker_start_and_limit_hits_the_store_once(self) -> None:
        calls: list[tuple] = []

        def fake(ticker, start, limit):
            calls.append((ticker, start, limit))
            return _rows(ticker)

        reader = PitReader()
        with mock.patch.object(reader_module.market_db, "price_path_from", side_effect=fake):
            first = reader.price_path("SPY", date(2026, 9, 1), 30)
            second = reader.price_path("spy", date(2026, 9, 1), 30)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first, second)

    def test_different_start_or_limit_or_ticker_is_read_again(self) -> None:
        calls: list[tuple] = []
        reader = PitReader()
        with mock.patch.object(
            reader_module.market_db, "price_path_from",
            side_effect=lambda ticker, start, limit: calls.append((ticker, start, limit)) or _rows(ticker),
        ):
            reader.price_path("SPY", date(2026, 9, 1), 30)
            reader.price_path("SPY", date(2026, 9, 2), 30)
            reader.price_path("SPY", date(2026, 9, 1), 60)
            reader.price_path("AAPL", date(2026, 9, 1), 30)
        self.assertEqual(len(calls), 4)

    def test_callers_cannot_corrupt_the_cached_path(self) -> None:
        reader = PitReader()
        with mock.patch.object(
            reader_module.market_db, "price_path_from", side_effect=lambda ticker, start, limit: _rows(ticker),
        ):
            first = reader.price_path("SPY", date(2026, 9, 1), 30)
            first.clear()
            self.assertEqual(len(reader.price_path("SPY", date(2026, 9, 1), 30)), 3)


if __name__ == "__main__":
    unittest.main()
