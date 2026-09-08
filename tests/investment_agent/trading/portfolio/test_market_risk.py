from __future__ import annotations

import math
import unittest
from datetime import date, timedelta

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.market_risk import (
    calculate_market_covariance,
    calculate_market_risk,
)


def _rows(start: float, returns: list[float]) -> list[dict[str, object]]:
    value = start
    origin = date(2026, 1, 1)
    rows = [{"trade_date": origin.isoformat(), "close": value}]
    for offset, daily_return in enumerate(returns, start=1):
        value *= 1.0 + daily_return
        rows.append({"trade_date": (origin + timedelta(days=offset)).isoformat(), "close": value})
    return rows


class MarketRiskTest(unittest.TestCase):
    def test_covariance_uses_signal_order_and_horizon(self):
        base_returns = [0.001 + (index % 5 - 2) * 0.0004 for index in range(80)]
        covariance = calculate_market_covariance(
            {
                "MSFT": _rows(100.0, [0.7 * value for value in base_returns]),
                "AAPL": _rows(100.0, [1.1 * value for value in base_returns]),
            },
            symbols=("AAPL", "MSFT"),
            horizon_days=5,
        )
        self.assertEqual(covariance.symbols, ("AAPL", "MSFT"))
        self.assertEqual(covariance.horizon_days, 5)
        self.assertEqual(covariance.observation_count, 80)
        self.assertEqual(len(covariance.matrix), 2)
        self.assertGreater(covariance.matrix[0][1], 0.0)
        metadata = covariance.to_metadata()
        self.assertEqual(metadata["method"], "sample_covariance")
        self.assertEqual(metadata["matrix"], [list(row) for row in covariance.matrix])

    def test_calculates_annualized_volatility_beta_correlation_and_drawdown(self):
        spy_returns = [0.001 + (index % 5 - 2) * 0.0004 for index in range(80)]
        aapl_returns = [1.1 * value + 0.0001 for value in spy_returns]
        msft_returns = [0.7 * value - 0.0001 for value in spy_returns]
        metrics = calculate_market_risk(
            {
                "AAPL": _rows(100.0, aapl_returns),
                "MSFT": _rows(100.0, msft_returns),
                "SPY": _rows(100.0, spy_returns),
            },
            target_weights={"AAPL": 0.4, "MSFT": 0.4, "CASH": 0.2},
        )
        self.assertEqual(metrics.observation_count, 80)
        self.assertGreater(metrics.portfolio_volatility, 0.0)
        self.assertGreater(metrics.portfolio_beta, 0.0)
        self.assertAlmostEqual(metrics.max_pairwise_correlation, 1.0, places=8)
        self.assertGreaterEqual(metrics.drawdown_fraction, 0.0)
        self.assertTrue(all(math.isfinite(value) for value in (
            metrics.portfolio_volatility,
            metrics.portfolio_beta,
            metrics.max_pairwise_correlation,
            metrics.drawdown_fraction,
        )))

    def test_fails_closed_when_one_target_lacks_aligned_history(self):
        with self.assertRaisesRegex(ContractError, "missing market price history: MSFT"):
            calculate_market_risk(
                {"AAPL": _rows(100.0, [0.001] * 80), "SPY": _rows(100.0, [0.0011] * 80)},
                target_weights={"AAPL": 0.4, "MSFT": 0.4, "CASH": 0.2},
            )


if __name__ == "__main__":
    unittest.main()
