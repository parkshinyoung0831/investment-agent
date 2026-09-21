"""HAC 지연 수는 관측 간격으로 세고(RS-7), 후보를 여러 개 견줘 고르면 t 문턱이 오른다(RS-17)."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

from investment_agent.research.commands.adopt_ml_model import check_adoptable, required_t_stat
from investment_agent.research.evaluation.alpha import cross_sectional_alpha_metrics, overlap_lags
from investment_agent.research.training.baseline import observation_spacing_days


class OverlapLagsTest(unittest.TestCase):
    def test_daily_or_unknown_spacing_keeps_the_conservative_horizon_minus_one(self) -> None:
        self.assertEqual(overlap_lags(20, None), 19)
        self.assertEqual(overlap_lags(20, 1.0) , 27)  # 20거래일 ≈ 28달력일 → 매일 관측이면 27개가 겹친다

    def test_weekly_samples_overlap_only_four_neighbours(self) -> None:
        self.assertEqual(overlap_lags(20, 7.0), 3)     # ceil(28/7) - 1
        self.assertEqual(overlap_lags(20, 28.0), 0)    # 겹치지 않는 표본

    def test_observation_spacing_is_the_median_gap_of_distinct_dates(self) -> None:
        stamps = [f"2026-09-{day:02d}T21:00:00+00:00" for day in (1, 8, 15, 22)] * 3
        self.assertEqual(observation_spacing_days(stamps), 7.0)
        self.assertIsNone(observation_spacing_days(["2026-09-01T21:00:00+00:00"]))


class MetricsUseTheSpacingTest(unittest.TestCase):
    def test_score_records_the_spacing_and_the_shorter_lag(self) -> None:
        rng = np.random.default_rng(3)
        start = date(2025, 1, 3)
        dates, actual, predicted = [], [], []
        for week in range(60):
            for name in range(8):
                signal = float(rng.normal())
                dates.append((start + timedelta(days=7 * week)).isoformat())
                actual.append(0.3 * signal + float(rng.normal()))
                predicted.append(signal)
        score = cross_sectional_alpha_metrics(dates, actual, predicted, horizon_days=20, sample_spacing_days=7.0)
        self.assertEqual(score.hac_lags, 3)
        self.assertEqual(score.sample_spacing_days, 7.0)


class ComparisonThresholdTest(unittest.TestCase):
    def test_threshold_rises_with_the_number_of_candidates(self) -> None:
        self.assertEqual(required_t_stat(1), 2.0)
        self.assertGreater(required_t_stat(4), 2.4)
        self.assertGreater(required_t_stat(8), required_t_stat(4))

    def test_a_borderline_candidate_passes_alone_but_not_among_four(self) -> None:
        from tests.investment_agent.research.commands.test_adopt_ml_model import _payload

        payload = _payload()
        payload["out_of_sample_alpha"]["ic_t_stat"] = 2.2
        self.assertTrue(check_adoptable(payload).is_adoptable)
        self.assertFalse(check_adoptable(payload, comparisons=4).is_adoptable)


if __name__ == "__main__":
    unittest.main()
