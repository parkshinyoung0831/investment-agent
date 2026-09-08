"""성과 평가가 거래일과 SPY 공통 날짜로만 계산되는지 검증한다."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.research.evaluation.evaluator import evaluate_case
from investment_agent.trading.portfolio.evaluator import evaluate_returns


class FakeRepository:
    def price_path(self, ticker: str, start_date: date, limit: int = 80) -> list[dict]:
        daily = 0.01 if ticker == "AAPL" else 0.005
        rows = []
        value = 100.0
        for index in range(65):
            rows.append({
                "ticker": ticker,
                "trade_date": (start_date + timedelta(days=index)).isoformat(),
                "close": value,
                "div_amount": 0,
            })
            value *= 1 + daily
        return rows


class EvaluatorTest(unittest.TestCase):
    def test_returns_all_mature_horizons_and_scores_probability(self):
        case = {
            "case_key": "AAPL__case",
            "ticker": "AAPL",
            "as_of_at": "2026-01-01T22:00:00+00:00",
            "final_decision": {"action": "open", "probability_up": 0.7},
        }

        rows = evaluate_case(FakeRepository(), case)

        self.assertEqual([row.horizon_days for row in rows], [5, 20, 60])
        self.assertTrue(all(row.excess_return > 0 for row in rows))
        self.assertTrue(all(row.direction_correct for row in rows))
        self.assertAlmostEqual(rows[0].brier_score, 0.09)


class PortfolioEvaluatorTest(unittest.TestCase):
    def test_cost_is_applied_to_each_rebalance_before_nav_and_risk_metrics(self):
        metrics = evaluate_returns(
            [0.10, -0.05],
            [0.0, 0.0],
            turnovers=[1.0, 1.0],
            cost_rate=0.01,
        )
        self.assertAlmostEqual(metrics.total_return, 1.09 * 0.94 - 1.0)
        self.assertAlmostEqual(metrics.max_drawdown, -0.06)
        self.assertAlmostEqual(metrics.transaction_cost, 0.01 + 1.09 * 0.01)
        self.assertAlmostEqual(metrics.turnover, 2.0)

    def test_turnover_must_align_with_return_periods(self):
        with self.assertRaisesRegex(ValueError, "match the return periods"):
            evaluate_returns([0.01, 0.02], [0.0, 0.0], turnovers=[0.1])


if __name__ == "__main__":
    unittest.main()


