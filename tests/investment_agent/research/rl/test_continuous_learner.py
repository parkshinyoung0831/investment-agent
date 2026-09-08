"""ContinuousLearner 단위 테스트."""
from __future__ import annotations

import unittest
import numpy as np

from investment_agent.research.rl.continuous_learner import (
    ContinuousLearner,
    PolicyEvaluationScore,
    PromotionDecision,
)


class ContinuousLearnerTests(unittest.TestCase):
    def test_promotion_decision_passes_when_improved(self) -> None:
        learner = ContinuousLearner(min_sharpe_improvement=0.10, min_dsr_probability=0.90)

        champion = PolicyEvaluationScore(
            sharpe_ratio=1.20,
            total_reward=15.0,
            excess_return=0.08,
            max_drawdown=0.05,
            turnover=1.0,
            dsr_probability=0.92,
            is_statistically_significant=True,
        )

        # 챌린저: 샤프 1.35 (+0.15 개선), DSR 0.96 통과
        challenger = PolicyEvaluationScore(
            sharpe_ratio=1.35,
            total_reward=18.0,
            excess_return=0.11,
            max_drawdown=0.04,
            turnover=0.9,
            dsr_probability=0.96,
            is_statistically_significant=True,
        )

        decision = learner.judge_promotion(challenger, champion)
        self.assertTrue(decision.is_promoted)
        self.assertAlmostEqual(decision.improvement_sharpe, 0.15)
        self.assertIn("샤프비율 향상", decision.reason)

    def test_promotion_decision_rejects_inferior_model(self) -> None:
        learner = ContinuousLearner(min_sharpe_improvement=0.10, min_dsr_probability=0.90)

        champion = PolicyEvaluationScore(
            sharpe_ratio=1.20,
            total_reward=15.0,
            excess_return=0.08,
            max_drawdown=0.05,
            turnover=1.0,
            dsr_probability=0.92,
            is_statistically_significant=True,
        )

        # 챌린저: 샤프 1.10 (열화됨)
        inferior_challenger = PolicyEvaluationScore(
            sharpe_ratio=1.10,
            total_reward=12.0,
            excess_return=0.05,
            max_drawdown=0.08,
            turnover=1.2,
            dsr_probability=0.80,
            is_statistically_significant=False,
        )

        decision = learner.judge_promotion(inferior_challenger, champion)
        self.assertFalse(decision.is_promoted)
        self.assertIn("승격 반려", decision.reason)

    def test_first_champion_needs_a_positive_excess_return(self) -> None:
        """벤치마크를 못 이긴 정책은 최초 챔피언이 될 수 없다."""
        learner = ContinuousLearner(min_sharpe_improvement=0.10, min_dsr_probability=0.90)

        # 실제로 승격됐던 값이다: 샤프는 높지만 벤치마크 대비 초과수익이 음수다.
        challenger = PolicyEvaluationScore(
            sharpe_ratio=1.9077,
            total_reward=-0.8565,
            excess_return=-0.072,
            max_drawdown=0.0136,
            turnover=0.8153,
            dsr_probability=1.0,
            is_statistically_significant=True,
        )

        decision = learner.judge_promotion(challenger, None)

        self.assertFalse(decision.is_promoted)
        self.assertIn("초과수익", decision.reason)

    def test_challenger_needs_a_positive_excess_return_against_a_champion(self) -> None:
        learner = ContinuousLearner(min_sharpe_improvement=0.10, min_dsr_probability=0.90)
        champion = PolicyEvaluationScore(
            sharpe_ratio=1.20, total_reward=15.0, excess_return=0.08, max_drawdown=0.05,
            turnover=1.0, dsr_probability=0.92, is_statistically_significant=True,
        )
        challenger = PolicyEvaluationScore(
            sharpe_ratio=1.60, total_reward=18.0, excess_return=-0.01, max_drawdown=0.04,
            turnover=0.9, dsr_probability=0.96, is_statistically_significant=True,
        )

        decision = learner.judge_promotion(challenger, champion)

        self.assertFalse(decision.is_promoted)
        self.assertIn("초과수익", decision.reason)

    def test_uniform_fallback_covers_cash_so_evaluation_does_not_crash(self) -> None:
        """predict도 호출도 안 되는 모델은 균등비중으로 평가한다 — 그 축에도 CASH가 있다."""
        from tests.investment_agent.research.rl.fixtures import historical_training_set

        _, training_set = historical_training_set(periods=4)

        class _Opaque:
            pass

        score = ContinuousLearner().evaluate_model(_Opaque(), training_set.dataset)

        self.assertEqual(score.periods_evaluated, 4)


if __name__ == "__main__":
    unittest.main()
