from __future__ import annotations

import unittest

import pandas as pd

from investment_agent.dashboard.components.alpha_lab import live_regime_from_prices
from investment_agent.reporting.services.investment import build_live_regime_read_model


class InvestmentMarketRegimeTest(unittest.TestCase):
    def test_invalid_or_insufficient_price_data_returns_none(self) -> None:
        self.assertIsNone(build_live_regime_read_model(None))
        self.assertIsNone(build_live_regime_read_model(pd.DataFrame()))
        self.assertIsNone(build_live_regime_read_model(pd.DataFrame({"Close": [100.0] * 20})))

    def test_market_prices_produce_the_existing_dashboard_read_model(self) -> None:
        index = pd.date_range("2026-06-01", periods=61, freq="D", tz="UTC")
        columns = pd.MultiIndex.from_product([["Close"], ["SPY", "QQQ", "^VIX"]])
        prices = pd.DataFrame(
            {
                ("Close", "SPY"): [100.0 + index * 0.20 for index in range(61)],
                ("Close", "QQQ"): [100.0 + index * 0.15 for index in range(61)],
                ("Close", "^VIX"): [15.0] * 61,
            },
            index=index,
            columns=columns,
        )

        result = build_live_regime_read_model(prices)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual("RISK_ON", result["risk_state"])
        self.assertEqual("up", result["trend"])
        self.assertEqual("normal", result["volatility_state"])
        self.assertEqual("native-regime-v1", result["metadata"]["calculation"])
        self.assertEqual(result, live_regime_from_prices(prices))


if __name__ == "__main__":
    unittest.main()
