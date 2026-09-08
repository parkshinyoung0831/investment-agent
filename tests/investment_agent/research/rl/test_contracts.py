from __future__ import annotations

import unittest

from investment_agent.research.rl.contracts import (
    FeatureSnapshot,
    ForwardReturnLabel,
    MembershipSnapshot,
    MembershipTimeline,
    RLSafetyError,
)


class RLStorageContractTest(unittest.TestCase):
    def test_feature_and_future_label_payloads_are_physically_separate(self):
        feature = FeatureSnapshot(
            feature_version="v1",
            as_of_at="2026-01-01T21:00:00+00:00",
            ticker="aapl",
            available_at="2026-01-01T20:00:00+00:00",
            is_available=True,
            features={"momentum": 0.2},
            source_ids=("market-row-1",),
            provenance={"dataset": "market.prices_daily", "point_in_time": True},
        )
        label = ForwardReturnLabel(
            feature_version="v1",
            as_of_at="2026-01-01T21:00:00+00:00",
            ticker="AAPL",
            forward_end_at="2026-01-02T21:00:00+00:00",
            label_available_at="2026-01-02T22:00:00+00:00",
            forward_return=0.03,
            benchmark_forward_return=0.01,
        )
        feature_row = feature.to_storage_row()
        label_row = label.to_storage_row()
        self.assertNotIn("forward_return", feature_row)
        self.assertNotIn("features", label_row)
        self.assertEqual(feature_row["provenance"]["point_in_time"], True)
        self.assertTrue(label_row["label_id"].startswith("rl_label_"))
        self.assertEqual(feature.ticker, "AAPL")

    def test_future_feature_and_early_label_are_rejected(self):
        with self.assertRaisesRegex(RLSafetyError, "available_at"):
            FeatureSnapshot(
                feature_version="v1",
                as_of_at="2026-01-01T21:00:00+00:00",
                ticker="AAPL",
                available_at="2026-01-01T22:00:00+00:00",
                is_available=True,
                features={"momentum": 0.2},
                source_ids=("source",),
                provenance={"dataset": "test", "point_in_time": True},
            )
        with self.assertRaisesRegex(RLSafetyError, "future label field"):
            FeatureSnapshot(
                feature_version="v1",
                as_of_at="2026-01-01T21:00:00+00:00",
                ticker="AAPL",
                available_at="2026-01-01T20:00:00+00:00",
                is_available=True,
                features={"forward_return": 0.2},
                source_ids=("source",),
                provenance={"dataset": "test", "point_in_time": True},
            )
        with self.assertRaisesRegex(RLSafetyError, "cannot be available"):
            ForwardReturnLabel(
                feature_version="v1",
                as_of_at="2026-01-01T21:00:00+00:00",
                ticker="AAPL",
                forward_end_at="2026-01-02T21:00:00+00:00",
                label_available_at="2026-01-02T20:00:00+00:00",
                forward_return=0.03,
                benchmark_forward_return=0.01,
            )

    def test_feature_requires_structured_provenance(self):
        with self.assertRaisesRegex(RLSafetyError, "structured provenance"):
            FeatureSnapshot(
                feature_version="v1",
                as_of_at="2026-01-01T21:00:00+00:00",
                ticker="AAPL",
                available_at="2026-01-01T20:00:00+00:00",
                is_available=True,
                features={"momentum": 0.2},
                source_ids=("source",),
                provenance={},
            )

    def test_membership_purpose_cannot_silently_switch_modes(self):
        live = MembershipTimeline(
            source_kind="live_tracked",
            snapshots=(MembershipSnapshot(
                effective_at="2026-01-01T21:00:00+00:00",
                symbols=("AAPL",),
                source_id="universe.securities.is_tracked=true@now",
                source_kind="live_tracked",
            ),),
        )
        with self.assertRaisesRegex(RLSafetyError, "historical_point_in_time"):
            live.members_at(
                "2026-01-01T21:01:00+00:00",
                purpose="historical_training",
            )
        historical = MembershipTimeline(
            source_kind="historical_point_in_time",
            snapshots=(MembershipSnapshot(
                effective_at="2026-01-02T00:00:00+00:00",
                symbols=("AAPL",),
                source_id="official-history",
                source_kind="historical_point_in_time",
            ),),
        )
        with self.assertRaisesRegex(RLSafetyError, "missing"):
            historical.members_at(
                "2026-01-01T21:00:00+00:00",
                purpose="historical_training",
            )


if __name__ == "__main__":
    unittest.main()
