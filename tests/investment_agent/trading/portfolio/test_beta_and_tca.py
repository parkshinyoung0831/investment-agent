from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.trading.portfolio.market_risk import (
    estimate_betas,
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
    return ExpectedReturnSignal(symbol, expected, 1.0, 0.1, 5, "t", AT, "v")


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


if __name__ == "__main__":
    unittest.main()
