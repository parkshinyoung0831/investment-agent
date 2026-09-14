from __future__ import annotations

import unittest

import numpy as np

from investment_agent.research.evaluation.alpha import cross_sectional_alpha_metrics, spearman_ic


class CrossSectionalAlphaTest(unittest.TestCase):
    def test_perfect_ranking_has_ic_one_and_positive_spread(self):
        dates, actual, predicted = [], [], []
        for day in range(4):
            for name in range(10):
                dates.append(day)
                actual.append(name * 0.01 + day)
                predicted.append(name)
        score = cross_sectional_alpha_metrics(dates, actual, predicted)
        self.assertAlmostEqual(score.mean_ic, 1.0)
        self.assertEqual(score.date_count, 4)
        self.assertAlmostEqual(score.positive_ic_ratio, 1.0)
        self.assertGreater(score.mean_quantile_spread, 0.0)

    def test_market_wide_moves_do_not_inflate_the_ic(self):
        # 날짜마다 시장 전체 수익이 크게 다르고, 예측은 그 수준만 맞힐 뿐 종목 순위는 무작위다.
        rng = np.random.default_rng(1)
        dates, actual, predicted = [], [], []
        for day in range(60):
            market = rng.normal(0.0, 0.05)
            for _ in range(20):
                dates.append(day)
                actual.append(market + rng.normal(0.0, 0.01))
                predicted.append(market + rng.normal(0.0, 0.01))
        pooled = spearman_ic(actual, predicted)
        score = cross_sectional_alpha_metrics(dates, actual, predicted)
        self.assertGreater(pooled, 0.8)
        self.assertLess(abs(score.mean_ic), 0.1)

    def test_icir_rewards_stable_ic(self):
        dates, actual, predicted = [], [], []
        rng = np.random.default_rng(7)
        for day in range(30):
            for name in range(12):
                signal = rng.normal()
                dates.append(day)
                predicted.append(signal)
                actual.append(0.3 * signal + rng.normal())
        score = cross_sectional_alpha_metrics(dates, actual, predicted)
        self.assertGreater(score.mean_ic, 0.0)
        self.assertAlmostEqual(score.icir, score.mean_ic / score.ic_std)
        self.assertAlmostEqual(score.ic_t_stat, score.icir * np.sqrt(score.date_count))

    def test_ties_get_average_ranks(self):
        self.assertIsNone(spearman_ic([1, 2, 3], [5, 5, 5]))
        self.assertAlmostEqual(spearman_ic([1, 2, 3, 4], [1, 1, 2, 2]), 0.894427191, places=6)

    def test_rejects_dates_without_enough_names(self):
        with self.assertRaisesRegex(ValueError, "no date has enough"):
            cross_sectional_alpha_metrics([0, 0, 0], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0])


if __name__ == "__main__":
    unittest.main()
