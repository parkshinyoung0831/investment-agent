"""성과 평가가 거래일과 SPY 공통 날짜로만 계산되는지 검증한다."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.research.evaluation.evaluator import evaluate_case
from investment_agent.research.evaluation.outcomes import EvaluationResult
from investment_agent.research.evaluation.returns import total_return


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
    def test_split_and_dividend_total_return_is_deterministic(self):
        # 저장 계약: close·div_amount는 이미 분할 조정(back-adjust)돼 있어 분할일에
        # 가격이 끊기지 않는다. 따라서 분할 비율은 수익률을 바꾸지 않아야 한다.
        rows = [
            {"close": 100.0},
            {"close": 105.0, "split_ratio": 2.0, "div_amount": 1.0},
            {"close": 110.0, "div_amount": 0.5},
        ]
        self.assertAlmostEqual(total_return(rows, 2), 0.115)
        without_split = [
            {key: value for key, value in row.items() if key != "split_ratio"}
            for row in rows
        ]
        self.assertAlmostEqual(total_return(rows, 2), total_return(without_split, 2))
        with self.assertRaisesRegex(ValueError, "insufficient price path"):
            total_return(rows, 3)

    def test_total_return_rejects_corrupt_split_ratio(self):
        rows = [{"close": 100.0}, {"close": 105.0, "split_ratio": 0.0}]
        with self.assertRaisesRegex(ValueError, "invalid split ratio"):
            total_return(rows, 1)

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
        self.assertIsInstance(rows[0], EvaluationResult)


if __name__ == "__main__":
    unittest.main()


