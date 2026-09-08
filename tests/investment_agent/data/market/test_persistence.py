"""persistence.py의 조회 함수가 MarketRepository로 위임한 뒤에도 같은 값을
주는지 굳힌다. 리팩터 전 특성화 테스트."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.market import persistence as db
from investment_agent.data.market.repository import SCHEMA, T_PRICES
from investment_agent.data.universe.repository import SCHEMA as SCHEMA_UNIVERSE, T_SECURITIES
from tests.investment_agent.fakes import FakeDatabase


def _price(security_id: int, day: str, close: float = 100.0) -> dict:
    return {
        "security_id": security_id, "trade_date": day,
        "open": close, "high": close, "low": close, "close": close,
        "volume": 1000, "is_repaired": False,
    }


class LatestPriceDateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeDatabase()
        db.configure(self.fake)
        self.addCleanup(db.configure, None)

    def test_returns_the_newest_date_across_all_securities(self) -> None:
        self.fake.put(SCHEMA, T_PRICES, [
            _price(1, "2026-09-02"), _price(2, "2026-09-09"), _price(3, "2026-09-05"),
        ])
        self.assertEqual("2026-09-09", db.latest_price_date())

    def test_none_when_the_table_is_empty(self) -> None:
        self.fake.put(SCHEMA, T_PRICES, [])
        self.assertIsNone(db.latest_price_date())


class PricesSinceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeDatabase()
        self.fake.put(SCHEMA, T_PRICES, [
            _price(1, "2026-09-02"), _price(1, "2026-09-09", close=101.0),
        ])
        self.fake.put(SCHEMA_UNIVERSE, T_SECURITIES, [
            {"security_id": 1, "ticker": "AAPL", "cik": "0000320193",
             "exchange_code": "XNAS", "security_type": "common_stock",
             "is_active_listing": True, "is_tracked": True},
        ])
        db.configure(self.fake)
        self.addCleanup(db.configure, None)

    def test_keys_rows_by_ticker_and_date_after_the_cutoff(self) -> None:
        result = db.prices_since("2026-09-05")
        self.assertEqual({("AAPL", "2026-09-09")}, set(result))
        self.assertEqual(101.0, result[("AAPL", "2026-09-09")]["close"])

    def test_a_security_missing_from_universe_is_silently_skipped(self) -> None:
        """universe에서 사라진 security_id는 조인이 안 되므로 결과에서 빠진다
        — 이전 raw 쿼리 구현과 같은 동작이다."""
        self.fake.put(SCHEMA, T_PRICES, [_price(999, "2026-09-09")])
        self.assertEqual({}, db.prices_since("2026-09-05"))


class UniverseMissingPricesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeDatabase()
        self.fake.put(SCHEMA_UNIVERSE, T_SECURITIES, [
            {"security_id": 1, "ticker": "AAPL", "is_tracked": True},
            {"security_id": 2, "ticker": "MSFT", "is_tracked": True},
        ])
        db.configure(self.fake)
        self.addCleanup(db.configure, None)

    def test_only_tracked_securities_with_zero_price_rows_are_returned(self) -> None:
        self.fake.put(SCHEMA, T_PRICES, [_price(1, "2026-09-02")])
        self.assertEqual(["MSFT"], db.universe_missing_prices())

    def test_empty_when_everyone_has_a_price(self) -> None:
        self.fake.put(SCHEMA, T_PRICES, [_price(1, "2026-09-02"), _price(2, "2026-09-02")])
        self.assertEqual([], db.universe_missing_prices())


if __name__ == "__main__":
    unittest.main()
