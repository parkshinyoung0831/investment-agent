"""RL 순수 단위 테스트용 point-in-time fixture."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from investment_agent.research.rl.contracts import (
    FeatureSnapshot,
    ForwardReturnLabel,
    MembershipSnapshot,
    MembershipTimeline,
)
from investment_agent.research.rl.features import (
    FeatureSpec,
    HistoricalTrainingSet,
    assemble_historical_training_set,
)


def historical_training_set(periods: int = 12) -> tuple[FeatureSpec, HistoricalTrainingSet]:
    spec = FeatureSpec(version="rl-v1", names=("momentum", "quality"))
    start = datetime(2026, 1, 1, 21, tzinfo=timezone.utc)
    features: list[FeatureSnapshot] = []
    labels: list[ForwardReturnLabel] = []
    for index in range(periods):
        as_of = start + timedelta(days=index)
        forward_end = as_of + timedelta(hours=12)
        for ticker, direction in (("AAPL", 1.0), ("MSFT", -1.0)):
            momentum = direction * (index + 1) / periods
            features.append(FeatureSnapshot(
                feature_version=spec.version,
                as_of_at=as_of.isoformat(),
                ticker=ticker,
                available_at=(as_of - timedelta(hours=1)).isoformat(),
                is_available=True,
                features={"momentum": momentum, "quality": 0.5},
                source_ids=(f"source-{ticker}-{index}",),
                provenance={"fixture": "historical_training_set", "point_in_time": True},
            ))
            labels.append(ForwardReturnLabel(
                feature_version=spec.version,
                as_of_at=as_of.isoformat(),
                ticker=ticker,
                forward_end_at=forward_end.isoformat(),
                label_available_at=(forward_end + timedelta(minutes=1)).isoformat(),
                forward_return=0.02 * momentum,
                benchmark_forward_return=0.001,
            ))
    membership = MembershipTimeline(
        source_kind="historical_point_in_time",
        snapshots=(MembershipSnapshot(
            effective_at=start.isoformat(),
            symbols=("AAPL", "MSFT"),
            source_id="official-history-1",
            source_kind="historical_point_in_time",
        ),),
    )
    training = assemble_historical_training_set(
        features,
        labels,
        symbols=("AAPL", "MSFT"),
        spec=spec,
        membership=membership,
        label_cutoff_at=(start + timedelta(days=periods + 1)).isoformat(),
    )
    return spec, training
