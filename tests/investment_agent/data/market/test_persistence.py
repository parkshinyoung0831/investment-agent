"""persistence.py의 조회 함수가 MarketRepository로 위임한 뒤에도 같은 값을
주는지 굳힌다. 리팩터 전 특성화 테스트."""
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

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

    def test_keys_rows_by_security_id_and_date_after_the_cutoff(self) -> None:
        """증분 비교는 수집 계획의 security_id로 한다. ticker로 되돌리면 개명 뒤 비교가 어긋난다."""
        result = db.prices_since("2026-09-05")
        self.assertEqual({(1, "2026-09-09")}, set(result))
        self.assertEqual(101.0, result[(1, "2026-09-09")]["close"])


class UniverseMissingPricesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeDatabase()
        self.fake.put(SCHEMA_UNIVERSE, T_SECURITIES, [
            {"security_id": 1, "ticker": "AAPL", "is_tracked": True},
            {"security_id": 2, "ticker": "MSFT", "is_tracked": True},
        ])
        db.configure(self.fake)
        self.addCleanup(db.configure, None)
        patcher = mock.patch.object(db, "REFERENCE_PRICE_TICKERS", ())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _missing(self) -> list[str]:
        with mock.patch.object(db, "us_market_today", return_value=date(2026, 9, 23)):
            return db.universe_missing_prices()

    def test_a_security_with_no_price_rows_is_returned(self) -> None:
        self.fake.put(SCHEMA, T_PRICES, [_price(1, "2025-09-15"), _price(1, "2026-09-02")])
        self.assertEqual(["MSFT"], self._missing())

    def test_a_security_with_only_recent_rows_is_returned(self) -> None:
        """일일 적재가 백필보다 먼저 최근 며칠을 넣은 새 편입 종목 — 행은 있지만 1년 전 가격이 없다."""
        self.fake.put(SCHEMA, T_PRICES, [_price(1, "2025-09-15"), _price(2, "2026-09-14"), _price(2, "2026-09-22")])
        self.assertEqual(["MSFT"], self._missing())

    def test_empty_when_everyone_has_a_year_of_history(self) -> None:
        self.fake.put(SCHEMA, T_PRICES, [_price(1, "2025-09-15"), _price(2, "2025-09-12")])
        self.assertEqual([], self._missing())


if __name__ == "__main__":
    unittest.main()


class PriceWriteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeDatabase()
        db.configure(self.fake)
        self.addCleanup(db.configure, None)

    def test_price_rows_without_the_planned_security_id_are_refused(self) -> None:
        """저장 직전에 ticker로 신원을 다시 풀지 않는다."""
        with self.assertRaises(ValueError):
            db.upsert_prices([{"ticker": "AAA", **{k: v for k, v in _price(1, "2026-09-02").items() if k != "security_id"}}])

    def test_missing_reference_securities_stop_the_plan(self) -> None:
        self.fake.put(SCHEMA_UNIVERSE, T_SECURITIES, [{"security_id": 1, "ticker": "AAPL", "is_tracked": True}])
        with mock.patch.object(db, "REFERENCE_PRICE_TICKERS", ("SPY",)), self.assertRaisesRegex(RuntimeError, "SPY"):
            db.price_targets()

    def test_an_ended_listing_is_not_a_reference_target(self) -> None:
        self.fake.put(SCHEMA_UNIVERSE, T_SECURITIES, [
            {"security_id": 5, "ticker": "SPY", "is_tracked": False, "is_active_listing": False,
             "is_identity_verified": False},
        ])
        with mock.patch.object(db, "REFERENCE_PRICE_TICKERS", ("SPY",)):
            self.assertEqual([], db.price_targets())
