from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.research.rl.leakage import audit_walk_forward_leakage
from investment_agent.research.training.splits import (
    WalkForwardSplit,
    make_purged_walk_forward_splits,
)
from tests.investment_agent.research.rl.fixtures import historical_training_set


class PurgedWalkForwardTest(unittest.TestCase):
    def test_long_labels_are_purged_before_validation_and_test(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        as_of = tuple((start + timedelta(days=i)).isoformat() for i in range(30))
        forward_end = tuple((start + timedelta(days=i + 3)).isoformat() for i in range(30))
        splits = make_purged_walk_forward_splits(
            as_of,
            forward_end,
            train_size=10,
            validation_size=5,
            test_size=3,
            embargo_size=1,
        )
        self.assertTrue(splits)
        first = splits[0]
        self.assertLess(first.train[1], 10)
        self.assertLess(first.validation[1], 16)
        self.assertEqual(first.test, first.out_of_sample)

    def test_independent_leakage_audit_detects_manual_bad_split(self):
        _, training = historical_training_set(12)
        clean = make_purged_walk_forward_splits(
            training.dataset.as_of_values,
            training.forward_end_values,
            train_size=5,
            validation_size=2,
            test_size=2,
            embargo_size=1,
        )
        self.assertTrue(audit_walk_forward_leakage(training, clean).clean)
        bad = (WalkForwardSplit(train=(0, 5), validation=(4, 7), out_of_sample=(7, 9)),)
        report = audit_walk_forward_leakage(training, bad)
        self.assertFalse(report.clean)
        with self.assertRaisesRegex(RuntimeError, "future leakage"):
            report.assert_clean()


if __name__ == "__main__":
    unittest.main()
