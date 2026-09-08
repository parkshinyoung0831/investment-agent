"""feature와 label을 cutoff 이후에만 안전하게 join하는 dataset builder."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.research.contracts import DatasetManifest, FeatureRecord, LabelRecord


@dataclass(frozen=True)
class ResearchDataset:
    """모델 입력으로 사용할 때만 label을 결합한 immutable matrix."""

    rows: tuple[FeatureRecord, ...]
    labels: tuple[LabelRecord, ...]
    feature_names: tuple[str, ...]
    features: np.ndarray
    targets: np.ndarray
    manifest: DatasetManifest

    def __post_init__(self) -> None:
        rows = tuple(self.rows)
        labels = tuple(self.labels)
        feature_names = tuple(self.feature_names)
        features = np.asarray(self.features, dtype=np.float64).copy()
        targets = np.asarray(self.targets, dtype=np.float64).reshape(-1).copy()
        if len(rows) != len(labels) or features.shape != (len(rows), len(feature_names)):
            raise ContractError("research dataset rows, labels, and feature matrix disagree")
        if targets.shape != (len(rows),) or not feature_names or len(set(feature_names)) != len(feature_names):
            raise ContractError("research dataset shape or feature names are invalid")
        if not np.isfinite(features).all() or not np.isfinite(targets).all():
            raise ContractError("research dataset contains non-finite values")
        if any(row.feature_version != self.manifest.feature_version for row in rows):
            raise ContractError("dataset row feature_version does not match manifest")
        features.setflags(write=False)
        targets.setflags(write=False)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "feature_names", feature_names)
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "targets", targets)

    @property
    def dataset_hash(self) -> str:
        return self.manifest.dataset_hash

    def split(self, indexes: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
        selected = np.asarray(tuple(indexes), dtype=int)
        if selected.ndim != 1 or any(index < 0 or index >= len(self.rows) for index in selected):
            raise ValueError("dataset split indexes are out of range")
        return self.features[selected], self.targets[selected]


def _feature_row(value: FeatureRecord | Mapping[str, Any]) -> FeatureRecord:
    if isinstance(value, FeatureRecord):
        return value
    return FeatureRecord(
        ticker=str(value["ticker"]),
        as_of_at=str(value["as_of_at"]),
        available_at=str(value.get("available_at") or value["as_of_at"]),
        feature_version=str(value["feature_version"]),
        features=dict(value["features"]),
        source_ids=tuple(value.get("source_ids") or ()),
        provenance=dict(value.get("provenance") or {}),
    )


def _label_row(value: LabelRecord | Mapping[str, Any], *, label_definition: str) -> LabelRecord:
    if isinstance(value, LabelRecord):
        return value
    return LabelRecord(
        ticker=str(value["ticker"]),
        as_of_at=str(value["as_of_at"]),
        forward_end_at=str(value["forward_end_at"]),
        label_available_at=str(value.get("label_available_at") or value["forward_end_at"]),
        feature_version=str(value["feature_version"]),
        label_definition=str(value.get("label_definition") or label_definition),
        label=float(value.get("label", value.get("forward_return"))),
        benchmark_label=float(value.get("benchmark_label", value.get("benchmark_forward_return", 0.0))),
        label_id=str(value["label_id"]) if value.get("label_id") else None,
    )


def _period_from_rows(rows: Sequence[FeatureRecord], name: str) -> tuple[str, str]:
    ordered = sorted(row.as_of_at for row in rows)
    if not ordered:
        raise ContractError(f"cannot infer {name} from an empty dataset")
    start_dt = parse_datetime(ordered[0])
    end_dt = parse_datetime(ordered[-1])
    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(microseconds=1)
    return start_dt.isoformat(), end_dt.isoformat()


def _inferred_periods(rows: Sequence[FeatureRecord]) -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
    """명시적 split이 없을 때 날짜 경계를 섞지 않고 세 구간으로 나눈다."""
    dates = sorted({parse_datetime(row.as_of_at) for row in rows})
    if len(dates) < 3:
        raise ContractError(
            "train_period, validation_period, and test_period are required "
            "when fewer than three distinct feature dates are available"
        )
    first_count = max(1, len(dates) // 3)
    second_count = max(first_count + 1, (2 * len(dates)) // 3)
    second_count = min(second_count, len(dates) - 1)
    groups = (
        dates[:first_count],
        dates[first_count:second_count],
        dates[second_count:],
    )
    return tuple(
        _period_from_rows(
            tuple(row for row in rows if parse_datetime(row.as_of_at) in set(group)),
            name,
        )
        for group, name in zip(groups, ("train_period", "validation_period", "test_period"))
    )  # type: ignore[return-value]


def build_research_dataset(
    feature_rows: Sequence[FeatureRecord | Mapping[str, Any]],
    label_rows: Sequence[LabelRecord | Mapping[str, Any]],
    *,
    feature_version: str,
    label_definition: str,
    label_cutoff_at: str,
    dataset_version: str = "research-dataset-v1",
    feature_names: Sequence[str] | None = None,
    train_period: Sequence[str] | None = None,
    validation_period: Sequence[str] | None = None,
    test_period: Sequence[str] | None = None,
    code_version: str = "investment-agent-research-v1",
    membership_source: str = "point_in_time",
) -> ResearchDataset:
    """label이 실제로 확정된 cutoff 이전 행만 exact key로 결합한다."""
    cutoff = parse_datetime(label_cutoff_at)
    features = tuple(_feature_row(row) for row in feature_rows)
    labels = tuple(_label_row(row, label_definition=label_definition) for row in label_rows)
    if not features:
        raise ContractError("research dataset requires feature rows")
    if any(row.feature_version != feature_version for row in features):
        raise ContractError("feature row version does not match requested feature_version")
    labels_by_key: dict[tuple[str, str, str], LabelRecord] = {}
    for label in labels:
        key = (label.ticker, label.as_of_at, label.feature_version)
        if key in labels_by_key:
            raise ContractError("duplicate research label identity")
        if label.feature_version != feature_version:
            raise ContractError("label row version does not match feature_version")
        if label.label_definition != label_definition:
            raise ContractError("label definition mismatch")
        if parse_datetime(label.label_available_at) > cutoff:
            continue
        labels_by_key[key] = label
    selected: list[tuple[FeatureRecord, LabelRecord]] = []
    seen: set[tuple[str, str, str]] = set()
    for feature in sorted(features, key=lambda row: (row.as_of_at, row.ticker)):
        if parse_datetime(feature.available_at) > cutoff:
            continue
        key = (feature.ticker, feature.as_of_at, feature.feature_version)
        if key in seen:
            raise ContractError("duplicate research feature identity")
        seen.add(key)
        label = labels_by_key.get(key)
        if label is not None:
            selected.append((feature, label))
    if not selected:
        raise ContractError("no feature/label pairs are available before label cutoff")
    rows = tuple(item[0] for item in selected)
    selected_labels = tuple(item[1] for item in selected)
    names = tuple(feature_names or sorted(rows[0].features))
    if not names or len(set(names)) != len(names):
        raise ContractError("feature_names must be unique and non-empty")
    if any(set(row.features) != set(names) for row in rows):
        raise ContractError("every feature row must have the same feature columns")
    matrix = np.asarray([[row.features[name] for name in names] for row in rows], dtype=np.float64)
    targets = np.asarray([label.label for label in selected_labels], dtype=np.float64)
    payload = {
        "feature_version": feature_version,
        "label_definition": label_definition,
        "cutoff": cutoff.isoformat(),
        "rows": [row.to_dict() for row in rows],
        "labels": [label.to_dict() for label in selected_labels],
        "feature_names": list(names),
    }
    dataset_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    inferred_periods = _inferred_periods(rows) if not all(
        period is not None for period in (train_period, validation_period, test_period)
    ) else None
    if inferred_periods is None:
        inferred_periods = (
            tuple(train_period),
            tuple(validation_period),
            tuple(test_period),
        )  # type: ignore[arg-type]
    manifest = DatasetManifest(
        dataset_version=dataset_version,
        feature_version=feature_version,
        label_definition=label_definition,
        pit_cutoff_at=cutoff.isoformat(),
        train_period=tuple(train_period or inferred_periods[0]),
        validation_period=tuple(validation_period or inferred_periods[1]),
        test_period=tuple(test_period or inferred_periods[2]),
        dataset_hash=dataset_hash,
        created_at=datetime.now(timezone.utc).isoformat(),
        code_version=code_version,
        membership_source=membership_source,
    )
    return ResearchDataset(rows, selected_labels, names, matrix, targets, manifest)


def load_dataset_json(path: str | Path) -> ResearchDataset:
    """offline CLI가 사용할 명시적 feature_rows/label_rows JSON을 읽는다."""
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ContractError("dataset JSON root must be an object")
    return build_research_dataset(
        payload.get("feature_rows") or payload.get("features") or (),
        payload.get("label_rows") or payload.get("labels") or (),
        feature_version=str(payload["feature_version"]),
        label_definition=str(payload["label_definition"]),
        label_cutoff_at=str(payload["label_cutoff_at"]),
        dataset_version=str(payload.get("dataset_version") or "research-dataset-v1"),
        feature_names=payload.get("feature_names"),
        train_period=payload.get("train_period"),
        validation_period=payload.get("validation_period"),
        test_period=payload.get("test_period"),
        code_version=str(payload.get("code_version") or "investment-agent-research-v1"),
        membership_source=str(payload.get("membership_source") or "point_in_time"),
    )


__all__ = ["ResearchDataset", "build_research_dataset", "load_dataset_json"]
