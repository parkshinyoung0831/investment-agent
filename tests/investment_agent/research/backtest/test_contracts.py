from __future__ import annotations

import unittest

from investment_agent.research.backtest.contracts import (
    BacktestConfig,
    BacktestRequest,
    MarketBar,
    UniverseSnapshot,
    WeightPoint,
)


def bar(symbol: str, session_date: str, price: float) -> MarketBar:
    return MarketBar(
        symbol=symbol,
        session_date=session_date,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=100.0,
    )


class BacktestContractsTest(unittest.TestCase):
    def test_weight_point_and_request_hash_are_order_independent(self):
        left = WeightPoint.create(
            decided_at="2026-01-02T21:00:00Z",
            effective_date="2026-01-05",
            weights={"MSFT": 0.25, "CASH": 0.5, "AAPL": 0.25},
            source_id="proposal-1",
            case_keys=("case-b", "case-a"),
        )
        right = WeightPoint.create(
            decided_at="2026-01-02T21:00:00+00:00",
            effective_date="2026-01-05",
            weights={"AAPL": 0.25, "MSFT": 0.25, "CASH": 0.5},
            source_id="proposal-1",
            case_keys=("case-a", "case-b"),
        )
        self.assertEqual(left.point_id, right.point_id)

        bars = (
            bar("MSFT", "2026-01-05", 200.0),
            bar("AAPL", "2026-01-02", 100.0),
            bar("AAPL", "2026-01-05", 101.0),
            bar("MSFT", "2026-01-02", 199.0),
        )
        snapshot = UniverseSnapshot(
            effective_date="2026-01-02",
            symbols=("MSFT", "AAPL"),
            source_id="membership-1",
        )
        first = BacktestRequest(
            sessions=("2026-01-02", "2026-01-05"),
            bars=bars,
            weight_points=(left,),
            universe_snapshots=(snapshot,),
        )
        second = BacktestRequest(
            sessions=("2026-01-05", "2026-01-02"),
            bars=tuple(reversed(bars)),
            weight_points=(right,),
            universe_snapshots=(snapshot,),
        )
        self.assertEqual(first.data_hash, second.data_hash)

    def test_current_cohort_requires_one_fixed_snapshot(self):
        point = WeightPoint.create(
            decided_at="2026-01-01T21:00:00Z",
            effective_date="2026-01-02",
            weights={"CASH": 1.0},
            source_id="cash",
        )
        snapshots = (
            UniverseSnapshot("2026-01-01", ("AAPL",), "one"),
            UniverseSnapshot("2026-02-01", ("AAPL", "MSFT"), "two"),
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            BacktestRequest(
                sessions=("2026-01-02",),
                bars=(bar("AAPL", "2026-01-02", 100.0),),
                weight_points=(point,),
                universe_snapshots=snapshots,
                config=BacktestConfig(cohort_mode="current_cohort"),
            )

    def test_market_bar_rejects_incoherent_ohlc(self):
        with self.assertRaisesRegex(ValueError, "low"):
            MarketBar(
                symbol="AAPL",
                session_date="2026-01-02",
                open=100.0,
                high=105.0,
                low=101.0,
                close=102.0,
            )


if __name__ == "__main__":
    unittest.main()
