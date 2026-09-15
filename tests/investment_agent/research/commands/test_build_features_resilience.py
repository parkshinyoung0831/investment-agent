"""feature 적재: 종목과 무관한 조회는 한 번만, 계산은 쌓이는 대로 저장한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.research.commands.build_features import build_features
from investment_agent.trading.evidence.context import ContextBuilder
from tests.investment_agent.trading.evidence.test_context_point_in_time import _Repository as _ContextRepository

AS_OF = datetime(2025, 1, 6, tzinfo=timezone.utc)


class _CountingRepository(_ContextRepository):
    def __init__(self, *, fail_saving_after: int | None = None):
        super().__init__()
        self.econ_calls = 0
        self.saved: list[list[dict]] = []
        self.fail_saving_after = fail_saving_after

    def market_prices(self, ticker, as_of_at, limit=260):
        day = datetime(2024, 11, 1)
        return [{"ticker": ticker, "trade_date": (day + timedelta(days=i)).date().isoformat(),
                 "close": 100 + i, "volume": 1000} for i in range(40)]

    def econ_snapshot(self, as_of_at, lookback_days=14):
        self.econ_calls += 1
        return super().econ_snapshot(as_of_at, lookback_days)

    def save_rl_feature_snapshots(self, rows):
        if self.fail_saving_after is not None and len(self.saved) >= self.fail_saving_after:
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


class IncrementalSaveTest(unittest.TestCase):
    def test_rows_are_saved_in_chunks_while_building(self):
        repository = _CountingRepository()
        tickers = [f"T{i:03d}" for i in range(250)]
        payload = build_features(as_of_at=AS_OF, tickers=tickers, repository=repository)
        self.assertEqual([len(chunk) for chunk in repository.saved], [100, 100, 50])
        self.assertEqual(payload["rows_upserted"], 250)

    def test_a_late_storage_failure_keeps_the_chunks_already_written(self):
        repository = _CountingRepository(fail_saving_after=1)
        with self.assertRaises(OSError):
            build_features(as_of_at=AS_OF, tickers=[f"T{i:03d}" for i in range(150)], repository=repository)
        self.assertEqual(len(repository.saved), 1)
        self.assertEqual(len(repository.saved[0]), 100)


if __name__ == "__main__":
    unittest.main()
