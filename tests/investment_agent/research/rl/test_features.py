from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.research.rl.contracts import (
    FeatureSnapshot,
    ForwardReturnLabel,
    MembershipSnapshot,
    MembershipTimeline,
    RLSafetyError,
)
from investment_agent.research.rl.features import (
    FeatureSpec,
    assemble_historical_training_set,
    build_feature_dataset,
    build_live_inference_frame,
)


class FeatureAssemblyTest(unittest.TestCase):
    def test_historical_training_requires_historical_membership(self):
        spec = FeatureSpec("v1", ("momentum",))
        base = datetime(2026, 1, 1, 21, tzinfo=timezone.utc)
        features = []
        labels = []
        for index in range(2):
            as_of = base + timedelta(days=index)
            features.append(FeatureSnapshot(
                "v1", as_of.isoformat(), "AAPL", as_of.isoformat(), True,
                {"momentum": float(index)}, (f"source-{index}",),
                {"fixture": "historical_membership", "point_in_time": True},
            ))
            labels.append(ForwardReturnLabel(
                "v1", as_of.isoformat(), "AAPL",
                (as_of + timedelta(hours=12)).isoformat(),
                (as_of + timedelta(hours=13)).isoformat(),
                0.01, 0.0,
            ))
        live = MembershipTimeline("live_tracked", (MembershipSnapshot(
            base.isoformat(), ("AAPL",), "tracked-now", "live_tracked",
        ),))
        with self.assertRaisesRegex(RLSafetyError, "historical_point_in_time"):
            assemble_historical_training_set(
                features,
                labels,
                symbols=("AAPL",),
                spec=spec,
                membership=live,
                label_cutoff_at=(base + timedelta(days=3)).isoformat(),
            )

    def test_membership_change_masks_non_member_even_if_feature_exists(self):
        spec = FeatureSpec("v1", ("momentum",))
        first = "2026-01-01T21:00:00+00:00"
        second = "2026-01-02T21:00:00+00:00"
        snapshots = []
        labels = []
        for as_of in (first, second):
            for ticker in ("AAPL", "MSFT"):
                snapshots.append(FeatureSnapshot(
                    "v1", as_of, ticker, as_of, True, {"momentum": 1.0},
                    (f"source-{as_of}-{ticker}",),
                    {"fixture": "membership_change", "point_in_time": True},
                ))
                labels.append(ForwardReturnLabel(
                    "v1", as_of, ticker,
                    (parse := datetime.fromisoformat(as_of) + timedelta(hours=12)).isoformat(),
                    (parse + timedelta(hours=1)).isoformat(), 0.01, 0.0,
                ))
        membership = MembershipTimeline("historical_point_in_time", (
            MembershipSnapshot(first, ("AAPL", "MSFT"), "history-1", "historical_point_in_time"),
            MembershipSnapshot(second, ("AAPL",), "history-2", "historical_point_in_time"),
        ))
        result = assemble_historical_training_set(
            snapshots,
            labels,
            symbols=("AAPL", "MSFT"),
            spec=spec,
            membership=membership,
            label_cutoff_at="2026-01-04T00:00:00+00:00",
        )
        self.assertTrue(result.dataset.availability[0, 1])
        self.assertFalse(result.dataset.availability[1, 1])

    def test_live_inference_uses_only_fresh_tracked_members(self):
        spec = FeatureSpec("v1", ("momentum",))
        point = "2026-01-02T21:00:00+00:00"
        membership = MembershipTimeline("live_tracked", (MembershipSnapshot(
            point, ("AAPL",), "is_tracked=true-query", "live_tracked",
        ),))
        snapshots = [
            FeatureSnapshot(
                "v1", point, ticker, point, True, {"momentum": 1.0}, (ticker,),
                {"fixture": "live_inference", "point_in_time": True},
            )
            for ticker in ("AAPL", "MSFT")
        ]
        frame = build_live_inference_frame(
            snapshots,
            symbols=("AAPL", "MSFT"),
            spec=spec,
            membership=membership,
            as_of_at=point,
        )
        self.assertEqual(frame.availability.tolist(), [True, False])
        historical = MembershipTimeline("historical_point_in_time", (MembershipSnapshot(
            point, ("AAPL",), "history", "historical_point_in_time",
        ),))
        with self.assertRaisesRegex(RLSafetyError, "live_tracked"):
            build_live_inference_frame(
                snapshots,
                symbols=("AAPL", "MSFT"),
                spec=spec,
                membership=historical,
                as_of_at=point,
            )

    def test_legacy_joined_rows_fail_without_membership_and_cutoff(self):
        with self.assertRaisesRegex(RLSafetyError, "historical membership"):
            build_feature_dataset(
                [{"as_of_at": "2026-01-01T00:00:00+00:00", "ticker": "AAPL"}],
                symbols=("AAPL",),
                spec=FeatureSpec("v1", ("momentum",)),
            )


if __name__ == "__main__":
    unittest.main()
