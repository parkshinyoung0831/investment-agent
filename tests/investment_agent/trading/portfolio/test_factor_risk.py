"""FactorRiskEngine 단위 테스트."""
from __future__ import annotations

import unittest

from investment_agent.trading.portfolio.factor_risk import (
    FactorExposure,
    FactorRiskEngine,
    PortfolioFactorExposure,
)


class FactorRiskTests(unittest.TestCase):
    def test_balanced_portfolio_passes_limit(self) -> None:
        engine = FactorRiskEngine(max_factor_limit=1.5)
        asset_factors = {
            "AAPL": FactorExposure(momentum=1.2, value=-0.5, quality=1.4, size=-1.0, volatility=0.8),
            "MSFT": FactorExposure(momentum=0.9, value=-0.2, quality=1.5, size=-1.2, volatility=0.6),
            "JNJ":  FactorExposure(momentum=-0.4, value=1.1, quality=0.8, size=-0.5, volatility=-0.9),
        }
        weights = {"AAPL": 0.3, "MSFT": 0.3, "JNJ": 0.3, "CASH": 0.1}
        exposure = engine.evaluate_portfolio(weights, asset_factors)

        self.assertTrue(exposure.is_balanced(max_limit=1.5))
        self.assertEqual(len(exposure.violations), 0)
        self.assertLess(exposure.max_absolute_exposure, 1.5)
        self.assertAlmostEqual(exposure.factors["quality"], (0.3*1.4 + 0.3*1.5 + 0.3*0.8) / 0.9, places=3)

    def test_overexposed_factor_is_flagged(self) -> None:
        engine = FactorRiskEngine(max_factor_limit=1.5)
        # 초고변동성 테크주 100% 몰빵 시 volatility 팩터 +2.2 초과 위반 감지
        asset_factors = {
            "MEME": FactorExposure(momentum=2.5, volatility=2.4),
        }
        weights = {"MEME": 0.9, "CASH": 0.1}
        exposure = engine.evaluate_portfolio(weights, asset_factors)

        self.assertFalse(exposure.is_balanced(max_limit=1.5))
        self.assertGreaterEqual(len(exposure.violations), 2)  # momentum & volatility
        self.assertIn("volatility", exposure.violations[1])


if __name__ == "__main__":
    unittest.main()
