from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.trading.portfolio.market_risk import (
    TradingCostInputs,
    calibrate_trading_costs,
    estimate_betas,
    realized_one_way_cost,
)
from investment_agent.trading.portfolio.optimizer import ExpectedReturnSignal, OptimizerPolicy, RiskAwareOptimizer

AT = "2026-09-14T20:00:00+00:00"


def _rows(returns: list[float]) -> list[dict]:
    value, rows = 100.0, [{"trade_date": date(2026, 1, 1).isoformat(), "close": 100.0}]
    for offset, daily in enumerate(returns, start=1):
        value *= 1.0 + daily
        rows.append({"trade_date": (date(2026, 1, 1) + timedelta(days=offset)).isoformat(), "close": value})
    return rows


def _signal(symbol: str, expected: float) -> ExpectedReturnSignal:
    return ExpectedReturnSignal(symbol, expected, 1.0, 0.1, 5, "t", AT, "v", action="open")


class BetaConstraintTest(unittest.TestCase):
    def test_betas_follow_the_benchmark_relationship(self):
        spy = [0.001 + (index % 7 - 3) * 0.003 for index in range(90)]
        betas = estimate_betas(
            {"HIGH": _rows([2.0 * value for value in spy]), "LOW": _rows([0.5 * value for value in spy]), "SPY": _rows(spy)},
            symbols=("HIGH", "LOW"),
        )
        self.assertAlmostEqual(betas["HIGH"], 2.0, places=6)
        self.assertAlmostEqual(betas["LOW"], 0.5, places=6)

    def test_optimizer_keeps_portfolio_beta_within_the_limit(self):
        policy = OptimizerPolicy(
            max_symbol_weight=1.0, max_turnover=1.0, min_cash_weight=0.0, risk_aversion=0.01,
            turnover_penalty=0.0, max_portfolio_beta=0.6,
        )
        signals = (_signal("HIGH", 0.10), _signal("LOW", 0.02))
        free = RiskAwareOptimizer(OptimizerPolicy(
            max_symbol_weight=1.0, max_turnover=1.0, min_cash_weight=0.0, risk_aversion=0.01, turnover_penalty=0.0,
        )).optimize(signals, current_weights={"CASH": 1.0}, betas={"HIGH": 2.0, "LOW": 0.5})
        bound = RiskAwareOptimizer(policy).optimize(
            signals, current_weights={"CASH": 1.0}, betas={"HIGH": 2.0, "LOW": 0.5},
        )
        free_beta = 2.0 * free.weights.get("HIGH", 0.0) + 0.5 * free.weights.get("LOW", 0.0)
        bound_beta = 2.0 * bound.weights.get("HIGH", 0.0) + 0.5 * bound.weights.get("LOW", 0.0)
        self.assertGreater(free_beta, 0.6)
        self.assertLessEqual(bound_beta, 0.6 + 1e-6)

    def test_fixed_holdings_above_the_limit_only_block_further_beta(self):
        policy = OptimizerPolicy(
            max_symbol_weight=1.0, max_turnover=1.0, min_cash_weight=0.0, risk_aversion=0.01,
            turnover_penalty=0.0, max_portfolio_beta=0.5,
        )
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("HIGH", 0.10),),
            current_weights={"OLD": 0.40, "HIGH": 0.05, "CASH": 0.55},
            fixed_weights={"OLD": 0.40},
            betas={"HIGH": 2.0, "OLD": 1.5},
        )
        # 고정 보유 베타(0.6)가 이미 상한을 넘으므로 HIGH는 현재 비중보다 늘지 않는다.
        self.assertLessEqual(result.weights["HIGH"], 0.05 + 1e-6)

    def test_missing_betas_fail_closed(self):
        policy = OptimizerPolicy(max_portfolio_beta=1.0)
        with self.assertRaisesRegex(Exception, "beta inputs are missing"):
            RiskAwareOptimizer(policy).optimize(
                (_signal("HIGH", 0.01), _signal("LOW", 0.01)),
                current_weights={"CASH": 1.0}, betas={"HIGH": 1.0},
            )


class TcaCalibrationTest(unittest.TestCase):
    def test_realized_cost_sign_convention(self):
        buy = {"side": "buy", "reference_price": 100, "average_fill_price": 100.1, "filled_quantity": 10, "commission": 0}
        sell = {"side": "sell", "reference_price": 100, "average_fill_price": 100.1, "filled_quantity": 10, "commission": 0}
        self.assertAlmostEqual(realized_one_way_cost(buy), 0.001)
        self.assertAlmostEqual(realized_one_way_cost(sell), -0.001)
        self.assertIsNone(realized_one_way_cost({"side": "buy"}))

    def test_costs_rise_with_enough_expensive_fills_but_never_fall(self):
        estimate = {
            "AAPL": TradingCostInputs("AAPL", 0.0001, 0.02, 1e10),
            "MSFT": TradingCostInputs("MSFT", 0.0003, 0.02, 1e9),
            "NVDA": TradingCostInputs("NVDA", 0.0001, 0.02, 1e10),
        }

        def fill(ticker, price):
            return {"ticker": ticker, "side": "buy", "reference_price": 100.0,
                    "average_fill_price": price, "filled_quantity": 10, "commission": 0.0}

        observations = (
            [fill("AAPL", 100.2)] * 5          # 20bp 실측 → 상향
            + [fill("MSFT", 99.9)] * 5         # 유리한 체결 → 내리지 않음
            + [fill("NVDA", 100.5)] * 4        # 표본 부족 → 그대로
        )
        calibrated = calibrate_trading_costs(estimate, observations, minimum_fills=5)
        self.assertAlmostEqual(calibrated["AAPL"].half_spread, 0.002)
        self.assertTrue(calibrated["AAPL"].method.startswith("tca_median"))
        self.assertEqual(calibrated["MSFT"], estimate["MSFT"])
        self.assertEqual(calibrated["NVDA"], estimate["NVDA"])


if __name__ == "__main__":
    unittest.main()
