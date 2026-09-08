from __future__ import annotations

import unittest

from investment_agent.research.backtest.contracts import NavPoint
from investment_agent.research.backtest.metrics import calculate_metrics


def nav(session_date: str, value: float, exposure: float = 0.5) -> NavPoint:
    return NavPoint(
        session_date=session_date,
        cash=value * (1.0 - exposure),
        market_value=value * exposure,
        nav=value,
        realized_pnl=0.0,
        unrealized_pnl=value - 100.0,
        total_pnl=value - 100.0,
        dividends=0.0,
        fees=0.0,
        slippage=0.0,
        gross_exposure=exposure,
    )


class BacktestMetricsTest(unittest.TestCase):
    def test_drawdown_and_exposure_include_initial_nav(self):
        metrics = calculate_metrics(
            (nav("2026-01-02", 110.0, 0.4), nav("2026-01-03", 88.0, 0.8)),
            (),
            initial_cash=100.0,
            periods_per_year=2,
        )
        self.assertAlmostEqual(metrics.total_return, -0.12)
        self.assertAlmostEqual(metrics.max_drawdown, -0.20)
        self.assertAlmostEqual(metrics.average_gross_exposure, 0.6)
        self.assertEqual(metrics.trade_count, 0)


if __name__ == "__main__":
    unittest.main()
