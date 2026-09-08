"""point-in-time RL feature와 미래 label을 엄격히 분리해 행렬화한다."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

import numpy as np

from investment_agent.trading.contracts import parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.research.rl.contracts import (
    FeatureSnapshot,
    ForwardReturnLabel,
    MembershipSnapshot,
    MembershipTimeline,
    RLDataNotReadyError,
    RLSafetyError,
    normalize_symbols,
)
from investment_agent.research.rl.environment import FeatureDataset


class FeatureRepository(Protocol):
    def rl_feature_snapshot_rows(
        self,
        symbols: tuple[str, ...],
        *,
        start_as_of: str,
        end_as_of: str,
        feature_version: str,
    ) -> list[dict[str, Any]]: ...


class LabelRepository(Protocol):
    def rl_training_label_rows(
        self,
        symbols: tuple[str, ...],
        *,
        start_as_of: str,
        end_as_of: str,
        feature_version: str,
        label_cutoff_at: str,
    ) -> list[dict[str, Any]]: ...


class MembershipRepository(Protocol):
    def rl_historical_membership_rows(
        self,
        *,
        start_as_of: str,
        end_as_of: str,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class FeatureSpec:
    version: str
    names: tuple[str, ...]
    benchmark: str = "SPY"

    def __post_init__(self) -> None:
        version = str(self.version).strip()
        names = tuple(str(name).strip() for name in self.names)
        if not version or not names or any(not name for name in names):
            raise ValueError("feature version and names are required")
        if len(names) != len(set(names)):
            raise ValueError("feature names must be unique")
        forbidden = [
            name for name in names
            if name.lower() in {"label", "target", "forward_return", "benchmark_forward_return"}
            or name.lower().startswith(("future_", "forward_", "label_", "target_"))
        ]
        if forbidden:
            raise RLSafetyError("feature spec contains future-label fields: " + ", ".join(forbidden))
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "names", names)

    @property
    def hash(self) -> str:
        return hashlib.sha256(canonical_json(self.__dict__).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HistoricalTrainingSet:
    """historical membership와 label 종료시각을 포함한 승격 가능 학습 입력."""

    dataset: FeatureDataset
    forward_end_values: tuple[str, ...]
    membership_hash: str
    feature_snapshot_ids: tuple[str, ...]
    label_ids: tuple[str, ...]
    data_hash: str

    def __post_init__(self) -> None:
        if len(self.forward_end_values) != len(self.dataset.as_of_values):
            raise ValueError("forward_end_values must match training periods")
        for name, value in (("membership_hash", self.membership_hash), ("data_hash", self.data_hash)):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be a sha256 digest")


@dataclass(frozen=True)
class LiveInferenceFrame:
    """label 없이 현재 tracked universe만 적용한 단일 추론 시점."""

    symbols: tuple[str, ...]
    feature_names: tuple[str, ...]
    feature_version: str
    as_of_at: str
    features: np.ndarray
    availability: np.ndarray
    membership_hash: str
    input_hash: str

    def __post_init__(self) -> None:
        features = np.asarray(self.features, dtype=np.float64).copy()
        availability = np.asarray(self.availability, dtype=bool).copy()
        if features.shape != (len(self.symbols), len(self.feature_names)):
            raise ValueError("live inference features must be symbols x feature_names")
        if availability.shape != (len(self.symbols),):
            raise ValueError("live inference availability must match symbols")
        if not np.isfinite(features).all():
            raise ValueError("live inference features must be finite")
        features.setflags(write=False)
        availability.setflags(write=False)
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "availability", availability)
        object.__setattr__(self, "as_of_at", parse_datetime(self.as_of_at).isoformat())


def _validate_feature_shape(snapshot: FeatureSnapshot, spec: FeatureSpec) -> None:
    if snapshot.feature_version != spec.version:
        raise RLSafetyError("feature snapshot version does not match FeatureSpec")
    fields = set(snapshot.features)
    expected = set(spec.names)
    if fields != expected:
        raise RLSafetyError(
            f"feature field mismatch for {snapshot.ticker}: "
            f"missing={sorted(expected - fields)} extra={sorted(fields - expected)}"
        )


def assemble_historical_training_set(
    feature_snapshots: Sequence[FeatureSnapshot],
    labels: Sequence[ForwardReturnLabel],
    *,
    symbols: Sequence[str],
    spec: FeatureSpec,
    membership: MembershipTimeline,
    label_cutoff_at: str | datetime,
) -> HistoricalTrainingSet:
    """현재 tracked 집합을 과거에 대입하지 않고 분리된 입력을 학습 행렬로 결합한다."""
    if not feature_snapshots or not labels:
        raise RLSafetyError("historical training requires separate feature snapshots and labels")
    normalized_symbols = normalize_symbols(symbols)
    symbol_set = set(normalized_symbols)
    cutoff = parse_datetime(label_cutoff_at)
    feature_by_key: dict[tuple[str, str], FeatureSnapshot] = {}
    for snapshot in feature_snapshots:
        if not isinstance(snapshot, FeatureSnapshot):
            raise TypeError("feature_snapshots must contain FeatureSnapshot values")
        _validate_feature_shape(snapshot, spec)
        if snapshot.ticker not in symbol_set:
            raise RLSafetyError(f"feature snapshot ticker is outside the action universe: {snapshot.ticker}")
        key = (snapshot.as_of_at, snapshot.ticker)
        if key in feature_by_key:
            raise RLSafetyError(f"duplicate feature snapshot: {key}")
        feature_by_key[key] = snapshot

    label_by_key: dict[tuple[str, str], ForwardReturnLabel] = {}
    for label in labels:
        if not isinstance(label, ForwardReturnLabel):
            raise TypeError("labels must contain ForwardReturnLabel values")
        if label.feature_version != spec.version:
            raise RLSafetyError("label feature_version does not match FeatureSpec")
        if label.ticker not in symbol_set:
            raise RLSafetyError(f"label ticker is outside the action universe: {label.ticker}")
        if parse_datetime(label.label_available_at) > cutoff:
            raise RLSafetyError("label was not is_available at the requested training cutoff")
        key = (label.as_of_at, label.ticker)
        if key in label_by_key:
            raise RLSafetyError(f"duplicate forward label: {key}")
        label_by_key[key] = label
    orphan_labels = sorted(set(label_by_key) - set(feature_by_key))
    if orphan_labels:
        raise RLSafetyError(f"labels without feature snapshots are forbidden: {orphan_labels}")

    as_of_values = tuple(sorted({key[0] for key in feature_by_key}, key=parse_datetime))
    if len(as_of_values) < 2:
        raise RLSafetyError("historical training requires at least two point-in-time periods")
    n_time = len(as_of_values)
    n_symbols = len(normalized_symbols)
    features = np.zeros((n_time, n_symbols, len(spec.names)), dtype=np.float64)
    returns = np.zeros((n_time, n_symbols), dtype=np.float64)
    availability = np.zeros((n_time, n_symbols), dtype=bool)
    benchmark = np.zeros(n_time, dtype=np.float64)
    forward_ends: list[str] = []
    used_features: list[str] = []
    used_labels: list[str] = []

    for t, as_of_at in enumerate(as_of_values):
        members = membership.members_at(as_of_at, purpose="historical_training")
        benchmark_values: list[float] = []
        label_end_values: list[str] = []
        for i, symbol in enumerate(normalized_symbols):
            snapshot = feature_by_key.get((as_of_at, symbol))
            if snapshot is None or symbol not in members or not snapshot.is_available:
                continue
            label = label_by_key.get((as_of_at, symbol))
            if label is None:
                raise RLSafetyError(f"is_available training feature has no future label: {as_of_at} {symbol}")
            for j, name in enumerate(spec.names):
                value = snapshot.features[name]
                features[t, i, j] = 0.0 if value is None else float(value)
            returns[t, i] = label.forward_return
            availability[t, i] = True
            benchmark_values.append(label.benchmark_forward_return)
            label_end_values.append(label.forward_end_at)
            used_features.append(snapshot.snapshot_id)
            used_labels.append(label.label_id)
        if not benchmark_values:
            raise RLSafetyError(f"training period has no member with feature and label: {as_of_at}")
        if max(benchmark_values) - min(benchmark_values) > 1e-12:
            raise RLSafetyError(f"inconsistent benchmark label at {as_of_at}")
        if len(set(label_end_values)) != 1:
            raise RLSafetyError(f"inconsistent forward horizon at {as_of_at}")
        benchmark[t] = benchmark_values[0]
        forward_ends.append(label_end_values[0])

    dataset = FeatureDataset(
        symbols=normalized_symbols,
        feature_names=spec.names,
        as_of_values=as_of_values,
        features=features,
        forward_returns=returns,
        benchmark_forward_returns=benchmark,
        availability=availability,
        feature_version=spec.version,
    )
    identity = {
        "feature_spec_hash": spec.hash,
        "membership_hash": membership.hash,
        "symbols": normalized_symbols,
        "as_of_values": as_of_values,
        "forward_end_values": forward_ends,
        "feature_snapshot_ids": sorted(used_features),
        "label_ids": sorted(used_labels),
    }
    data_hash = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return HistoricalTrainingSet(
        dataset=dataset,
        forward_end_values=tuple(forward_ends),
        membership_hash=membership.hash,
        feature_snapshot_ids=tuple(sorted(used_features)),
        label_ids=tuple(sorted(used_labels)),
        data_hash=data_hash,
    )


def load_training_set(
    repository: Any,
    *,
    symbols: Sequence[str],
    start_as_of: str | datetime,
    end_as_of: str | datetime,
    label_cutoff_at: str | datetime,
    spec: FeatureSpec,
) -> HistoricalTrainingSet:
    """원장 세 갈래(feature·label·역사 membership)를 학습 가능한 dataset으로 결합한다.

    한 갈래라도 비면 대체 데이터를 만들지 않고 실패한다. RL이 합성 표본을 학습하면
    성적표는 그럴듯하게 나오지만 그 정책은 시장에 대해 아무것도 모른다.
    """
    normalized = normalize_symbols(symbols)
    if not normalized:
        raise RLSafetyError("training requires at least one action-universe symbol")
    start = parse_datetime(start_as_of).isoformat()
    end = parse_datetime(end_as_of).isoformat()
    cutoff = parse_datetime(label_cutoff_at).isoformat()

    feature_rows = repository.rl_feature_snapshot_rows(
        normalized, start_as_of=start, end_as_of=end, feature_version=spec.version,
    )
    if not feature_rows:
        raise RLDataNotReadyError(
            "no RL feature snapshot is stored for the requested window; run build_features first"
        )
    label_rows = repository.rl_training_label_rows(
        normalized,
        start_as_of=start,
        end_as_of=end,
        feature_version=spec.version,
        label_cutoff_at=cutoff,
    )
    if not label_rows:
        raise RLDataNotReadyError(
            "no forward label is confirmed before the cutoff; run build_labels first"
        )
    membership_rows = repository.rl_historical_membership_rows(start_as_of=start, end_as_of=end)
    if not membership_rows:
        raise RLDataNotReadyError(
            "point-in-time membership is unavailable; current tracked tickers must not stand in for it"
        )

    membership = MembershipTimeline(
        source_kind="historical_point_in_time",
        snapshots=tuple(
            MembershipSnapshot(
                effective_at=str(row["effective_at"]),
                symbols=tuple(row["symbols"]),
                source_id=str(row["source_id"]),
                source_kind=str(row.get("source_kind") or "historical_point_in_time"),
            )
            for row in membership_rows
        ),
    )
    snapshots = [
        FeatureSnapshot(
            feature_version=str(row.get("feature_version") or spec.version),
            as_of_at=str(row["as_of_at"]),
            ticker=str(row["ticker"]),
            available_at=str(row["available_at"]),
            is_available=bool(row.get("is_available", False)),
            features={name: row["features"].get(name) for name in spec.names},
            source_ids=tuple(row.get("source_ids") or ()),
            provenance=dict(row.get("provenance") or {}),
        )
        for row in feature_rows
    ]
    labels = [
        ForwardReturnLabel(
            feature_version=str(row.get("feature_version") or spec.version),
            as_of_at=str(row["as_of_at"]),
            ticker=str(row["ticker"]),
            forward_end_at=str(row["forward_end_at"]),
            label_available_at=str(row["label_available_at"]),
            forward_return=float(row["forward_return"]),
            benchmark_forward_return=float(row["benchmark_forward_return"]),
        )
        for row in label_rows
    ]
    return assemble_historical_training_set(
        snapshots,
        labels,
        symbols=normalized,
        spec=spec,
        membership=membership,
        label_cutoff_at=cutoff,
    )


def build_live_inference_frame(
    feature_snapshots: Sequence[FeatureSnapshot],
    *,
    symbols: Sequence[str],
    spec: FeatureSpec,
    membership: MembershipTimeline,
    as_of_at: str | datetime,
    max_membership_age_seconds: float = 900.0,
    max_feature_age_seconds: float = 86_400.0,
) -> LiveInferenceFrame:
    """현재 universe.securities.is_tracked=true snapshot만 live action mask로 사용한다."""
    if max_membership_age_seconds <= 0 or max_feature_age_seconds <= 0:
        raise ValueError("live membership and feature age limits must be positive")
    point = parse_datetime(as_of_at)
    normalized_symbols = normalize_symbols(symbols)
    members = membership.members_at(
        point,
        purpose="live_inference",
        max_live_age_seconds=max_membership_age_seconds,
    )
    latest: dict[str, FeatureSnapshot] = {}
    for snapshot in feature_snapshots:
        _validate_feature_shape(snapshot, spec)
        if snapshot.ticker not in normalized_symbols:
            raise RLSafetyError(f"live feature ticker is outside model symbols: {snapshot.ticker}")
        snapshot_time = parse_datetime(snapshot.as_of_at)
        if snapshot_time > point:
            raise RLSafetyError("future feature snapshot cannot be used for live inference")
        current = latest.get(snapshot.ticker)
        if current is None or snapshot_time > parse_datetime(current.as_of_at):
            latest[snapshot.ticker] = snapshot

    features = np.zeros((len(normalized_symbols), len(spec.names)), dtype=np.float64)
    availability = np.zeros(len(normalized_symbols), dtype=bool)
    used_ids: list[str] = []
    for i, symbol in enumerate(normalized_symbols):
        snapshot = latest.get(symbol)
        if snapshot is None or symbol not in members or not snapshot.is_available:
            continue
        age = (point - parse_datetime(snapshot.as_of_at)).total_seconds()
        if age > max_feature_age_seconds:
            continue
        for j, name in enumerate(spec.names):
            value = snapshot.features[name]
            features[i, j] = 0.0 if value is None else float(value)
        availability[i] = True
        used_ids.append(snapshot.snapshot_id)
    identity = {
        "feature_spec_hash": spec.hash,
        "membership_hash": membership.hash,
        "as_of_at": point.isoformat(),
        "symbols": normalized_symbols,
        "feature_snapshot_ids": sorted(used_ids),
        "availability": availability.tolist(),
    }
    input_hash = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return LiveInferenceFrame(
        symbols=normalized_symbols,
        feature_names=spec.names,
        feature_version=spec.version,
        as_of_at=point.isoformat(),
        features=features,
        availability=availability,
        membership_hash=membership.hash,
        input_hash=input_hash,
    )


def build_feature_dataset(
    rows: list[Mapping[str, Any]],
    *,
    symbols: tuple[str, ...],
    spec: FeatureSpec,
    membership: MembershipTimeline | None = None,
    label_cutoff_at: str | datetime | None = None,
) -> FeatureDataset:
    """기존 JOIN 행도 provenance와 역사 membership 없이는 학습에 쓰지 못하게 한다."""
    if membership is None or label_cutoff_at is None:
        raise RLSafetyError(
            "historical membership and label_cutoff_at are required; joined rows alone are unsafe"
        )
    snapshots: list[FeatureSnapshot] = []
    labels: list[ForwardReturnLabel] = []
    for row in rows:
        snapshot = FeatureSnapshot(
            feature_version=str(row.get("feature_version") or spec.version),
            as_of_at=str(row["as_of_at"]),
            ticker=str(row["ticker"]),
            available_at=str(row["available_at"]),
            is_available=bool(row.get("is_available", False)),
            features={name: row.get(name) for name in spec.names},
            source_ids=tuple(row.get("source_ids") or ()),
            provenance=dict(row.get("provenance") or {}),
        )
        snapshots.append(snapshot)
        if row.get("forward_return") is not None:
            labels.append(ForwardReturnLabel(
                feature_version=snapshot.feature_version,
                as_of_at=snapshot.as_of_at,
                ticker=snapshot.ticker,
                forward_end_at=str(row["forward_end_at"]),
                label_available_at=str(row["label_available_at"]),
                forward_return=float(row["forward_return"]),
                benchmark_forward_return=float(row["benchmark_forward_return"]),
            ))
    return assemble_historical_training_set(
        snapshots,
        labels,
        symbols=symbols,
        spec=spec,
        membership=membership,
        label_cutoff_at=label_cutoff_at,
    ).dataset


__all__ = [
    "FeatureRepository",
    "MembershipRepository",
    "LabelRepository",
    "FeatureSpec",
    "HistoricalTrainingSet",
    "LiveInferenceFrame",
    "assemble_historical_training_set",
    "build_feature_dataset",
    "build_live_inference_frame",
    "load_training_set",
]
