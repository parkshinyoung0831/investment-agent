"""feature 적재: 공통 조회는 한 번만 하고 날짜 단위 결과는 한 번에 저장한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.research.commands.build_features import build_features
from investment_agent.trading.evidence.context import ContextBuilder
from tests.investment_agent.trading.evidence.test_context_point_in_time import _Repository as _ContextRepository

AS_OF = datetime(2025, 1, 6, tzinfo=timezone.utc)


class _CountingRepository(_ContextRepository):
    def __init__(self):
        super().__init__()
        self.econ_calls = 0

    def market_prices(self, ticker, as_of_at, limit=260):
        day = datetime(2024, 11, 1)
        return [{"ticker": ticker, "trade_date": (day + timedelta(days=i)).date().isoformat(),
                 "close": 100 + i, "volume": 1000} for i in range(40)]

    def econ_snapshot(self, as_of_at, lookback_days=14):
        self.econ_calls += 1
        return super().econ_snapshot(as_of_at, lookback_days)


class _CountingStore:
    def __init__(self, *, fail_saving: bool = False):
        self.saved: list[list[dict]] = []
        self.fail_saving = fail_saving

    def save_rl_feature_snapshots(self, rows):
        if self.fail_saving:
            raise OSError("research store is busy")
        self.saved.append(list(rows))


class SharedContextTest(unittest.TestCase):
    def test_ticker_independent_reads_happen_once_per_builder_and_as_of(self):
        repository = _CountingRepository()
        builder = ContextBuilder(repository)
        for ticker in ("AAA", "BBB", "CCC"):
            builder.build(ticker, AS_OF)
        self.assertEqual((repository.macro_calls, repository.econ_calls), (1, 1))
        builder.build("AAA", AS_OF + timedelta(days=1))
        self.assertEqual((repository.macro_calls, repository.econ_calls), (2, 2))


class DateAtomicSaveTest(unittest.TestCase):
    def test_all_rows_are_saved_once_for_the_date(self):
        repository = _CountingRepository()
        store = _CountingStore()
        tickers = [f"T{i:03d}" for i in range(250)]
        payload = build_features(
            as_of_at=AS_OF, tickers=tickers, repository=repository, store=store,
        )
        self.assertEqual([len(batch) for batch in store.saved], [250])
        self.assertEqual(payload["rows_upserted"], 250)

    def test_storage_failure_does_not_leave_a_command_level_partial_batch(self):
        store = _CountingStore(fail_saving=True)
        with self.assertRaises(OSError):
            build_features(
                as_of_at=AS_OF,
                tickers=[f"T{i:03d}" for i in range(150)],
                repository=_CountingRepository(),
                store=store,
            )
        self.assertEqual(store.saved, [])

    def test_dry_run_does_not_write_to_the_research_store(self):
        store = _CountingStore()
        payload = build_features(
            as_of_at=AS_OF,
            tickers=["AAA"],
            dry_run=True,
            repository=_CountingRepository(),
            store=store,
        )
        self.assertEqual(store.saved, [])
        self.assertEqual(payload["rows_upserted"], 0)


if __name__ == "__main__":
    unittest.main()
