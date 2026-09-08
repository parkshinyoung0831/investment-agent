from __future__ import annotations

import unittest

from investment_agent.research.backtest.contracts import (
    BacktestRequest,
    MarketBar,
    UniverseSnapshot,
    WeightPoint,
)
from investment_agent.research.backtest.engine import WeightBacktestEngine
from investment_agent.research.backtest.validation import LumiBotValidationEngine, compare_results


def _request() -> BacktestRequest:
    sessions = ("2026-01-02", "2026-01-05")
    bars = tuple(
        MarketBar("AAPL", day, price, price + 1, price - 1, price, 1_000_000)
        for day, price in zip(sessions, (100.0, 101.0), strict=True)
    )
    return BacktestRequest(
        sessions=sessions,
        bars=bars,
        weight_points=(WeightPoint.create(
            decided_at="2026-01-02T21:00:00+00:00",
            effective_date="2026-01-05",
            weights={"AAPL": 0.5, "CASH": 0.5},
            source_id="signal-v1",
        ),),
        universe_snapshots=(UniverseSnapshot("2026-01-02", ("AAPL",), "sp500-pit"),),
    )


class BacktestValidationTest(unittest.TestCase):
    def test_native_and_lumibot_adapter_share_request_and_cost_hash(self):
        request = _request()
        native = WeightBacktestEngine().run(request)
        validator = LumiBotValidationEngine(request)
        self.assertEqual(native.input_hash, validator.input_hash)
        comparison = compare_results(
            native,
            native.metrics,
            validation_input_hash=validator.input_hash,
        )
        self.assertTrue(comparison.is_compatible)

    def test_metric_difference_and_wrong_manifest_are_visible(self):
        native = WeightBacktestEngine().run(_request())
        changed = dict(native.metrics)
        changed["total_return"] = float(changed["total_return"]) + 0.1
        comparison = compare_results(
            native,
            changed,
            validation_input_hash=native.input_hash,
        )
        self.assertFalse(comparison.is_compatible)
        with self.assertRaisesRegex(ValueError, "exact Native input"):
            compare_results(native, native.metrics, validation_input_hash="0" * 64)


if __name__ == "__main__":
    unittest.main()
