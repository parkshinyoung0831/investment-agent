"""feature와 label을 cutoff 이후에만 안전하게 join하는 dataset builder."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from investment_agent.platform.serialization import ContractError, canonical_json, parse_datetime
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
        label_definition=str(value.get("label_definition") or label_definition),
        label=float(value.get("label", value.get("forward_return"))),
        # 없으면 0.0으로 접지 않고 KeyError로 드러낸다 — 0%는 실제 값이다.
        benchmark_label=float(
            value["benchmark_label"] if "benchmark_label" in value
            else value["benchmark_forward_return"]
        ),
        label_id=str(value["label_id"]) if value.get("label_id") else None,
    )


def build_research_dataset(
    feature_rows: Sequence[FeatureRecord | Mapping[str, Any]],
    label_rows: Sequence[LabelRecord | Mapping[str, Any]],
    *,
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
    labels_by_key: dict[tuple[str, str], LabelRecord] = {}
    for label in labels:
        key = (label.ticker, label.as_of_at)
        if key in labels_by_key:
            raise ContractError("duplicate research label identity")
        if label.label_definition != label_definition:
            raise ContractError("label definition mismatch")
        if parse_datetime(label.label_available_at) > cutoff:
            continue
        labels_by_key[key] = label
    selected: list[tuple[FeatureRecord, LabelRecord]] = []
    seen: set[tuple[str, str]] = set()
    for feature in sorted(features, key=lambda row: (row.as_of_at, row.ticker)):
        if parse_datetime(feature.available_at) > cutoff:
            continue
        key = (feature.ticker, feature.as_of_at)
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
        "label_definition": label_definition,
        "cutoff": cutoff.isoformat(),
        "rows": [row.to_dict() for row in rows],
        "labels": [label.to_dict() for label in selected_labels],
        "feature_names": list(names),
    }
    dataset_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    # 호출자가 주지 않으면 **추정하지 않고 비워 둔다**. 전에는 as_of를 1/3씩 나눈 구간을
    # 대신 적었는데, 실제 학습 구간은 `training/baseline.py`의 purged split이 정하므로
    # 같은 학습 기록에 기간이 두 벌 들어가 감사하는 사람이 틀린 쪽을 믿었다.
    manifest = DatasetManifest(
        dataset_version=dataset_version,
        label_definition=label_definition,
        pit_cutoff_at=cutoff.isoformat(),
        train_period=tuple(train_period) if train_period is not None else None,
        validation_period=tuple(validation_period) if validation_period is not None else None,
        test_period=tuple(test_period) if test_period is not None else None,
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
