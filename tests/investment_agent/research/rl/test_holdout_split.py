"""학습 구간과 평가 구간을 시간으로 갈라 in-sample 자화자찬을 막는다."""
from __future__ import annotations

import unittest

from investment_agent.research.rl.pipeline import split_dataset
from tests.investment_agent.research.rl.fixtures import historical_training_set


class SplitDatasetTest(unittest.TestCase):
    def setUp(self) -> None:
        _, training_set = historical_training_set(periods=10)
        self.dataset = training_set.dataset

    def test_splits_in_time_order_without_overlap(self):
        train, holdout = split_dataset(self.dataset, holdout_fraction=0.3)

        self.assertEqual(len(train.as_of_values), 7)
        self.assertEqual(len(holdout.as_of_values), 3)
        self.assertEqual(
            train.as_of_values + holdout.as_of_values, self.dataset.as_of_values
        )
        self.assertFalse(set(train.as_of_values) & set(holdout.as_of_values))

    def test_holdout_is_always_the_later_period(self):
        train, holdout = split_dataset(self.dataset, holdout_fraction=0.3)

        self.assertLess(max(train.as_of_values), min(holdout.as_of_values))

    def test_both_sides_keep_at_least_one_period(self):
        train, holdout = split_dataset(self.dataset, holdout_fraction=0.99)

        self.assertGreaterEqual(len(train.as_of_values), 1)
        self.assertGreaterEqual(len(holdout.as_of_values), 1)

    def test_dataset_too_short_to_split_is_rejected(self):
        single, _ = split_dataset(self.dataset, holdout_fraction=0.3)
        one_period, _ = split_dataset(single, holdout_fraction=0.99)
        while len(one_period.as_of_values) > 1:
            one_period, _ = split_dataset(one_period, holdout_fraction=0.99)

        with self.assertRaises(ValueError):
            split_dataset(one_period, holdout_fraction=0.3)

    def test_invalid_fraction_is_rejected(self):
        for fraction in (0.0, 1.0, -0.1, 1.5):
            with self.assertRaises(ValueError):
                split_dataset(self.dataset, holdout_fraction=fraction)


if __name__ == "__main__":
    unittest.main()
