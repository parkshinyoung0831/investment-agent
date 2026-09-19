"""읽기 경로 최적화가 결과를 바꾸지 않는지: 가격 창 조회·종목 ID 기억·저장소 기억·기술지표 일괄·병렬 feature 적재."""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from investment_agent.data.market import persistence as market_db

AS_OF = datetime(2026, 9, 14, 23, 30, tzinfo=timezone.utc)


def _weekday_bars(start: date, end: date, *, skip: tuple[date, date] | None = None) -> list[dict]:
    bars, day = [], start
    while day <= end:
        halted = skip is not None and skip[0] <= day <= skip[1]
        if day.weekday() < 5 and not halted:
            bars.append({"trade_date": day.isoformat(), "open": 1.0, "high": 1.0, "low": 1.0,
                         "close": float(day.toordinal()), "volume": 1.0})
        day += timedelta(days=1)
    return bars


class _FakeMarketRepository:
    def __init__(self, db):
        pass

    def dividends(self, ids, since=None):
        return []

    def splits(self, ids, since=None):
        return []


class PriceWindowTest(unittest.TestCase):
    def _run(self, bars: list[dict], limit: int) -> tuple[list[dict], list[dict], int]:
        calls: list[tuple[date, date]] = []

        def price_rows(ticker, *, start, end, known_at=None, security_id=None):
            calls.append((start, end))
            return [dict(bar, ticker=ticker) for bar in bars if start.isoformat() <= bar["trade_date"] <= end.isoformat()]

        with mock.patch.object(market_db, "_ticker_id", return_value=7), \
                mock.patch.object(market_db, "_price_rows", side_effect=price_rows), \
                mock.patch.object(market_db, "MarketRepository", _FakeMarketRepository):
            windowed = market_db.price_history_as_of("AAA", AS_OF, limit=limit)
            with mock.patch.object(market_db, "_history_window_start", return_value=date(1900, 1, 1)):
                full = market_db.price_history_as_of("AAA", AS_OF, limit=limit)
        return windowed, full, len(calls)

    def test_window_read_equals_full_history_read(self):
        bars = _weekday_bars(date(2015, 1, 1), AS_OF.date())
        windowed, full, calls = self._run(bars, 260)
        self.assertEqual(windowed, full)
        self.assertEqual(len(windowed), 260)
        self.assertEqual(calls, 2)  # 창 1번(충분) + 비교용 전체 1번

    def test_short_or_halted_history_falls_back_to_the_full_read(self):
        halted = _weekday_bars(date(2020, 1, 1), AS_OF.date(), skip=(date(2025, 1, 1), date(2026, 6, 30)))
        windowed, full, calls = self._run(halted, 260)
        self.assertEqual(windowed, full)
        self.assertEqual(calls, 3)  # 창이 모자라 전체로 다시 읽음

    def test_unknown_ticker_reads_nothing(self):
        with mock.patch.object(market_db, "_ticker_id", return_value=None), \
                mock.patch.object(market_db, "_price_rows", side_effect=AssertionError("should not read")):
            self.assertEqual(market_db.price_history_as_of("ZZZ", AS_OF), [])


class SecurityIdCacheTest(unittest.TestCase):
    def setUp(self):
        market_db.clear_id_cache()
        self.addCleanup(market_db.clear_id_cache)

    def test_found_ids_are_remembered_and_missing_ones_are_not(self):
        universe = mock.Mock()
        universe.security_ids.side_effect = lambda tickers: {t: 1 for t in tickers if t == "AAA"}
        with mock.patch.object(market_db, "_universe", return_value=universe), \
                mock.patch.object(market_db, "_database", None):
            self.assertEqual(market_db._ids(["AAA", "NEW"]), {"AAA": 1})
            self.assertEqual(market_db._ids(["aaa", "NEW"]), {"AAA": 1})
        self.assertEqual([call.args[0] for call in universe.security_ids.call_args_list], [["AAA", "NEW"], ["NEW"]])

    def test_expired_entries_are_read_again(self):
        universe = mock.Mock()
        universe.security_ids.side_effect = lambda tickers: {t: 1 for t in tickers}
        with mock.patch.object(market_db, "_universe", return_value=universe), \
                mock.patch.object(market_db, "_database", None), \
                mock.patch.object(market_db, "_ID_CACHE_SECONDS", -1.0):
            market_db._ids(["AAA"])
            market_db._ids(["AAA"])
        self.assertEqual(universe.security_ids.call_count, 2)

    def test_injected_database_is_never_cached(self):
        universe = mock.Mock()
        universe.security_ids.side_effect = lambda tickers: {t: 1 for t in tickers}
        with mock.patch.object(market_db, "_universe", return_value=universe), \
                mock.patch.object(market_db, "_database", object()):
            market_db._ids(["AAA"])
            market_db._ids(["AAA"])
        self.assertEqual(universe.security_ids.call_count, 2)


class RepositoryMemoTest(unittest.TestCase):
    def _repository(self):
        from investment_agent.trading.supabase_repository import SupabaseRepository
        return object.__new__(SupabaseRepository)

    def test_same_price_read_is_sent_once_and_callers_get_independent_copies(self):
        repository = self._repository()
        rows = [{"trade_date": "2026-09-14", "close": 1.0}]
        with mock.patch("investment_agent.trading.supabase_repository.market_db.price_history_as_of",
                        return_value=rows) as read:
            first = repository.market_prices("aaa", AS_OF)
            first[0]["close"] = 999.0
            second = repository.market_prices("AAA", AS_OF)
            repository.market_prices("AAA", AS_OF, limit=130)
            repository.market_prices("AAA", AS_OF + timedelta(days=1))
        self.assertEqual(second[0]["close"], 1.0)
        self.assertEqual(read.call_count, 3)  # 기간(limit)·판단 시각이 다르면 따로 읽는다

    def test_memo_expires(self):
        repository = self._repository()
        with mock.patch.object(type(repository._reader_cache()), "_MEMO_SECONDS", -1.0), \
                mock.patch("investment_agent.trading.supabase_repository.market_db.price_history_as_of",
                           return_value=[]) as read:
            repository.market_prices("AAA", AS_OF)
            repository.market_prices("AAA", AS_OF)
        self.assertEqual(read.call_count, 2)

    def test_guru_state_is_built_once_per_as_of(self):
        repository = self._repository()
        with mock.patch("investment_agent.trading.supabase_repository.institutional_persistence."
                        "effective_portfolio_state", return_value=({}, {}, [])) as read:
            for _ in range(3):
                repository._effective_guru_state(AS_OF)
        self.assertEqual(read.call_count, 1)

    def test_technical_snapshot_reads_all_tickers_once_with_the_same_contract(self):
        repository = self._repository()
        latest = {"AAA": {"ticker": "AAA", "trade_date": "2026-09-14", "rsi14": 55.0, "ingested_at": "x"}}
        with mock.patch("investment_agent.trading.supabase_repository.latest_technical_signals_as_of",
                        return_value=latest) as read:
            self.assertEqual(repository.technical_snapshot("AAA", AS_OF), [latest["AAA"]])
            self.assertEqual(repository.technical_snapshot("BBB", AS_OF), [])
            repository.technical_snapshot("AAA", AS_OF)[0]["rsi14"] = 0.0
            self.assertEqual(repository.technical_snapshot("AAA", AS_OF)[0]["rsi14"], 55.0)
        self.assertEqual(read.call_count, 1)
        with self.assertRaises(ValueError):
            repository.technical_snapshot("AAA", datetime(2026, 9, 14))


class LatestFeaturesBatchTest(unittest.TestCase):
    def test_batch_read_matches_per_ticker_read(self):
        from investment_agent.research.storage.repository import ResearchStore

        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.duckdb")
            rows = []
            for ticker in ("AAA", "BBB", "CCC"):
                for offset in range(5):
                    rows.append({"ticker": ticker, "trade_date": f"2026-09-{8 + offset:02d}",
                                 "rsi14": 40.0 + offset, "macd": 0.1, "macd_signal": 0.05})
            store.upsert_features(rows[:10], ingested_at="2026-09-13T00:00:00+00:00")
            # CCC는 판단 시각 뒤에 적재됐다 — 두 방식 모두 보지 않아야 한다.
            store.upsert_features(rows[10:], ingested_at="2026-09-20T00:00:00+00:00")
            reader = ResearchStore(Path(directory) / "research.duckdb", read_only=True)
            trade_date, as_of = date(2026, 9, 11), datetime(2026, 9, 14, tzinfo=timezone.utc)
            batch = reader.latest_features_as_of_all(trade_date=trade_date, as_of_at=as_of)
            for ticker in ("AAA", "BBB", "CCC"):
                single = reader.latest_feature_as_of(ticker, trade_date=trade_date, as_of_at=as_of)
                self.assertEqual([batch[ticker]] if ticker in batch else [], single, ticker)
            self.assertEqual(batch["AAA"]["trade_date"], "2026-09-11")
            self.assertNotIn("CCC", batch)


class ParallelFeatureBuildTest(unittest.TestCase):
    def test_parallel_build_saves_the_same_rows_in_the_same_order_as_sequential(self):
        from investment_agent.research.commands.build_features import build_features
        from tests.investment_agent.research.commands.test_build_features_resilience import (
            AS_OF as RESILIENCE_AS_OF,
            _CountingRepository,
        )

        tickers = [f"T{i:03d}" for i in range(230)]
        sequential, parallel = _CountingRepository(), _CountingRepository()
        build_features(as_of_at=RESILIENCE_AS_OF, tickers=tickers, repository=sequential, workers=1)
        payload = build_features(as_of_at=RESILIENCE_AS_OF, tickers=tickers, repository=parallel, workers=8)
        self.assertEqual(parallel.saved, sequential.saved)
        self.assertEqual(payload["detail"]["workers"], 8)
        self.assertEqual(parallel.econ_calls, 1)

    def test_work_actually_overlaps_and_failures_stay_isolated(self):
        from investment_agent.research.commands.build_features import build_features
        from tests.investment_agent.research.commands.test_build_features_resilience import (
            AS_OF as RESILIENCE_AS_OF,
            _CountingRepository,
        )

        active, peak, lock = [0], [0], threading.Lock()

        class Slow(_CountingRepository):
            def market_prices(self, ticker, as_of_at, limit=260):
                with lock:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                time.sleep(0.02)
                with lock:
                    active[0] -= 1
                if ticker == "T003":
                    raise RuntimeError("provider down")
                return super().market_prices(ticker, as_of_at, limit)

        repository = Slow()
        payload = build_features(as_of_at=RESILIENCE_AS_OF, tickers=[f"T{i:03d}" for i in range(12)],
                                 repository=repository, workers=4)
        self.assertGreater(peak[0], 1)
        self.assertEqual(payload["detail"]["failed"], ["T003"])
        self.assertEqual(payload["rows_upserted"], 11)

    def test_workers_setting(self):
        from investment_agent.research.commands import build_features as module

        with mock.patch.dict("os.environ", {module.WORKERS_ENV: "99"}):
            self.assertEqual(module.default_workers(), 16)
        with mock.patch.dict("os.environ", {module.WORKERS_ENV: "abc"}):
            self.assertEqual(module.default_workers(), module.DEFAULT_WORKERS)
        with self.assertRaises(ValueError):
            module.build_features(as_of_at=AS_OF, tickers=["A"], repository=mock.Mock(), workers=0)


if __name__ == "__main__":
    unittest.main()
