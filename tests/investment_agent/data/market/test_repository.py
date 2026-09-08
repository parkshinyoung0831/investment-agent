"""PIT 경계가 둘 다 걸리는지, 봉이 조용히 잘리지 않는지 본다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from investment_agent.data.market.domain.models import DailyBar, MarketDataError
from investment_agent.data.market.repository import (
    SCHEMA,
    T_DIVIDENDS,
    T_PRICES,
    T_SPLITS,
    MarketRepository,
)
from investment_agent.platform.db.postgres import READ_PAGE_SIZE
from tests.investment_agent.fakes import FakeDatabase


def _row(day: int, close: float = 100.0, *, ingested: str = "2026-09-01T00:00:00+00:00") -> dict:
    return {
        "security_id": 1,
        "trade_date": f"2026-09-{day:02d}",
        "open": close, "high": close, "low": close, "close": close,
        "volume": 1000,
        "source": "yfinance",
        "ingested_at": ingested,
    }


class PointInTimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_PRICES, [
            # 9/2 봉은 제때 들어왔다.
            _row(2, 100.0, ingested="2026-09-02T22:00:00+00:00"),
            # 9/3 봉은 사흘 늦게 들어왔다. 9/4 시점에는 몰랐던 값이다.
            _row(3, 101.0, ingested="2026-09-06T22:00:00+00:00"),
        ])
        self.repo = MarketRepository(self.db)

    def test_without_known_at_everything_we_now_know_is_returned(self) -> None:
        bars = self.repo.bars([1], start=date(2026, 9, 1), end=date(2026, 9, 30))
        self.assertEqual(2, len(bars))

    def test_known_at_does_not_hide_late_backfilled_market_facts(self) -> None:
        """시장 가격은 수집 시각이 아니라 거래일 공개 시각으로 해석한다."""
        bars = self.repo.bars(
            [1],
            start=date(2026, 9, 1),
            end=date(2026, 9, 30),
            known_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )
        self.assertEqual([date(2026, 9, 2), date(2026, 9, 3)], [bar.trade_date for bar in bars])

    def test_the_date_range_still_applies(self) -> None:
        bars = self.repo.bars([1], start=date(2026, 9, 3), end=date(2026, 9, 30))
        self.assertEqual([date(2026, 9, 3)], [bar.trade_date for bar in bars])


class BulkReadTest(unittest.TestCase):
    def test_more_than_one_page_is_read_completely(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_PRICES, [
            {**_row(1), "trade_date": f"2020-01-{i % 28 + 1:02d}", "security_id": i}
            for i in range(READ_PAGE_SIZE + 40)
        ])
        bars = MarketRepository(db).bars(
            [i for i in range(READ_PAGE_SIZE + 40)],
            start=date(2020, 1, 1), end=date(2020, 12, 31),
        )
        self.assertEqual(READ_PAGE_SIZE + 40, len(bars))

    def test_long_security_lists_are_split(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_PRICES, [])
        MarketRepository(db).bars(
            list(range(250)), start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
        self.assertEqual(3, len(db.in_calls))

    def test_closes_on_returns_only_that_day(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_PRICES, [_row(2, 100.0), _row(3, 101.0)])
        self.assertEqual({1: 101.0}, MarketRepository(db).closes_on(date(2026, 9, 3), [1]))

    def test_latest_trade_date_is_the_newest(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_PRICES, [_row(2), _row(7), _row(3)])
        self.assertEqual(date(2026, 9, 7), MarketRepository(db).latest_trade_date(1))

    def test_latest_trade_date_is_none_for_an_empty_security(self) -> None:
        self.assertIsNone(MarketRepository(FakeDatabase()).latest_trade_date(99))


class MarketWideQueriesTest(unittest.TestCase):
    def test_latest_price_date_is_the_newest_across_all_securities(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_PRICES, [
            {**_row(2), "security_id": 1},
            {**_row(9), "security_id": 2},
            {**_row(5), "security_id": 3},
        ])
        self.assertEqual(date(2026, 9, 9), MarketRepository(db).latest_price_date())

    def test_latest_price_date_is_none_when_empty(self) -> None:
        self.assertIsNone(MarketRepository(FakeDatabase()).latest_price_date())

    def test_prices_since_returns_raw_rows_not_daily_bar_objects(self) -> None:
        """market_daily의 changed_rows() 비교가 이 값에 의존한다 — DailyBar
        검증을 통과하지 못하는 값(과거에 저장된 예외적인 행 등)이 있어도
        여기서 예외가 나면 안 된다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_PRICES, [
            {**_row(2), "security_id": 1},
            {**_row(9), "security_id": 1},
        ])
        rows = MarketRepository(db).prices_since(date(2026, 9, 5))
        self.assertEqual(1, len(rows))
        self.assertIsInstance(rows[0], dict)
        self.assertEqual("2026-09-09", str(rows[0]["trade_date"]))

    def test_security_ids_with_prices_returns_only_ids_that_have_rows(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_PRICES, [{**_row(2), "security_id": 1}])
        self.assertEqual({1}, MarketRepository(db).security_ids_with_prices([1, 2, 3]))

    def test_security_ids_with_prices_empty_input_never_touches_the_store(self) -> None:
        db = FakeDatabase()
        self.assertEqual(set(), MarketRepository(db).security_ids_with_prices([]))
        self.assertEqual([], db.executed)


class BadRowTest(unittest.TestCase):
    def test_an_incoherent_bar_is_refused(self) -> None:
        """high가 다른 값보다 낮은 봉은 어떤 계산에도 쓸 수 없다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_PRICES, [{**_row(2), "high": 50.0}])
        with self.assertRaises(MarketDataError):
            MarketRepository(db).bars([1], start=date(2026, 9, 1), end=date(2026, 9, 30))

    def test_a_nan_price_is_refused(self) -> None:
        """NaN 하나가 이후 모든 집계를 조용히 NaN으로 만든다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_PRICES, [{**_row(2), "close": float("nan")}])
        with self.assertRaises(MarketDataError):
            MarketRepository(db).bars([1], start=date(2026, 9, 1), end=date(2026, 9, 30))

    def test_a_zero_price_is_refused(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_PRICES, [{**_row(2), "low": 0.0}])
        with self.assertRaises(MarketDataError):
            MarketRepository(db).bars([1], start=date(2026, 9, 1), end=date(2026, 9, 30))

    def test_a_ratio_of_one_is_not_a_split(self) -> None:
        """조정을 아무것도 안 하면서 '분할이 있었다'고 말하는 행이다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_SPLITS, [
            {"security_id": 1, "action_date": "2026-09-04", "split_ratio": 1.0, "source": "yfinance"},
        ])
        with self.assertRaises(MarketDataError):
            MarketRepository(db).splits([1])

    def test_a_negative_dividend_is_refused(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_DIVIDENDS, [
            {"security_id": 1, "ex_date": "2026-09-04", "div_amount": -1.0, "source": "yfinance"},
        ])
        with self.assertRaises(MarketDataError):
            MarketRepository(db).dividends([1])


class WriteTest(unittest.TestCase):
    def test_ingested_at_is_never_sent(self) -> None:
        """코드가 PIT 경계를 정할 수 있으면 그 경계는 경계가 아니다."""
        db = FakeDatabase()
        MarketRepository(db).upsert_bars([
            DailyBar(1, date(2026, 9, 4), 100, 101, 99, 100, 1000)
        ])
        (_key, rows, conflict) = db.upserts[0]
        self.assertNotIn("ingested_at", rows[0])
        self.assertEqual("security_id,trade_date", conflict)

    def test_bars_are_stored_by_security_id_not_ticker(self) -> None:
        db = FakeDatabase()
        MarketRepository(db).upsert_bars([
            DailyBar(7, date(2026, 9, 4), 100, 101, 99, 100, 1000)
        ])
        (_key, rows, _conflict) = db.upserts[0]
        self.assertEqual(7, rows[0]["security_id"])
        self.assertNotIn("ticker", rows[0])


if __name__ == "__main__":
    unittest.main()
