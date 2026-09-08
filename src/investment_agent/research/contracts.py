"""연구 산출물의 provenance와 PIT 경계를 표현하는 계약."""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from investment_agent.trading.contracts import ContractError, json_value, parse_datetime
from investment_agent.platform.serialization import canonical_json


def _strings(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    result = tuple(str(value).strip() for value in values if str(value).strip())
    if any(not isinstance(value, str) for value in values):
        raise ContractError(f"{field_name} must contain strings")
    return result


def _period(value: Sequence[str], field_name: str) -> tuple[str, str]:
    if len(value) != 2:
        raise ContractError(f"{field_name} requires start and end")
    start = parse_datetime(str(value[0])).isoformat()
    end = parse_datetime(str(value[1])).isoformat()
    if end <= start:
        raise ContractError(f"{field_name} end must be after start")
    return start, end


def _finite_features(value: Mapping[str, Any], field_name: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or not value:
        raise ContractError(f"{field_name} must be a non-empty mapping")
    result: dict[str, float] = {}
    for key, raw in value.items():
        name = str(key).strip()
        if not name:
            raise ContractError(f"{field_name} contains an empty feature name")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ContractError(f"{field_name}.{name} must be numeric")
        number = float(raw)
        if not math.isfinite(number):
            raise ContractError(f"{field_name}.{name} must be finite")
        result[name] = number
    return {name: result[name] for name in sorted(result)}


@dataclass(frozen=True)
class FeatureRecord:
    """label을 포함하지 않는 하나의 시점 feature 행."""

    ticker: str
    as_of_at: str
    available_at: str
    feature_version: str
    features: Mapping[str, Any]
    source_ids: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ticker = str(self.ticker).upper().strip()
        as_of = parse_datetime(self.as_of_at).isoformat()
        available = parse_datetime(self.available_at).isoformat()
        if not ticker or available > as_of:
            raise ContractError("feature ticker and available_at<=as_of_at are required")
        version = str(self.feature_version).strip()
        if not version:
            raise ContractError("feature_version is required")
        source_ids = _strings(self.source_ids, "source_ids")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "as_of_at", as_of)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "feature_version", version)
        object.__setattr__(self, "features", _finite_features(self.features, "features"))
        object.__setattr__(self, "source_ids", source_ids)
        object.__setattr__(self, "provenance", dict(self.provenance))

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class LabelRecord:
    """feature 시점 뒤에 확정되는 미래 label 행."""

    ticker: str
    as_of_at: str
    forward_end_at: str
    label_available_at: str
    feature_version: str
    label_definition: str
    label: float
    benchmark_label: float = 0.0
    label_id: str | None = None

    def __post_init__(self) -> None:
        ticker = str(self.ticker).upper().strip()
        as_of = parse_datetime(self.as_of_at).isoformat()
        forward_end = parse_datetime(self.forward_end_at).isoformat()
        label_available = parse_datetime(self.label_available_at).isoformat()
        if not ticker or forward_end <= as_of or label_available < forward_end:
            raise ContractError("label times must satisfy as_of < forward_end <= label_available")
        feature_version = str(self.feature_version).strip()
        definition = str(self.label_definition).strip()
        if not feature_version or not definition:
            raise ContractError("label feature_version and label_definition are required")
        for name in ("label", "benchmark_label"):
            raw = getattr(self, name)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
                raise ContractError(f"{name} must be finite numeric")
            object.__setattr__(self, name, float(raw))
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "as_of_at", as_of)
        object.__setattr__(self, "forward_end_at", forward_end)
        object.__setattr__(self, "label_available_at", label_available)
        object.__setattr__(self, "feature_version", feature_version)
        object.__setattr__(self, "label_definition", definition)
        label_id = str(self.label_id).strip() if self.label_id is not None else ""
        object.__setattr__(
            self,
            "label_id",
            label_id or "label_" + hashlib.sha256(canonical_json(asdict(self)).encode("utf-8")).hexdigest()[:24],
        )

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class DatasetManifest:
    """dataset hash·기간·PIT cutoff을 모델 artifact와 함께 추적한다."""

    dataset_version: str
    feature_version: str
    label_definition: str
    pit_cutoff_at: str
    train_period: tuple[str, str]
    validation_period: tuple[str, str]
    test_period: tuple[str, str]
    dataset_hash: str
    created_at: str
    code_version: str = "investment-agent-research-v1"
    membership_source: str = "point_in_time"
    manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        values = {
            "dataset_version": str(self.dataset_version).strip(),
            "feature_version": str(self.feature_version).strip(),
            "label_definition": str(self.label_definition).strip(),
            "dataset_hash": str(self.dataset_hash).strip(),
            "code_version": str(self.code_version).strip(),
            "membership_source": str(self.membership_source).strip(),
        }
        if any(not value for value in values.values()):
            raise ContractError("dataset manifest text fields are required")
        if values["membership_source"] not in {"point_in_time", "current_cohort"}:
            raise ContractError("membership_source must be point_in_time or current_cohort")
        cutoff = parse_datetime(self.pit_cutoff_at).isoformat()
        created = parse_datetime(self.created_at).isoformat()
        periods = {
            "train_period": _period(self.train_period, "train_period"),
            "validation_period": _period(self.validation_period, "validation_period"),
            "test_period": _period(self.test_period, "test_period"),
        }
        if periods["train_period"][1] > periods["validation_period"][0]:
            raise ContractError("train and validation periods overlap")
        if periods["validation_period"][1] > periods["test_period"][0]:
            raise ContractError("validation and test periods overlap")
        if len(values["dataset_hash"]) != 64 or any(char not in "0123456789abcdef" for char in values["dataset_hash"]):
            raise ContractError("dataset_hash must be a sha256 hex digest")
        identity = {**values, "pit_cutoff_at": cutoff, **periods, "created_at": created}
        manifest_hash = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        for key, value in values.items():
            object.__setattr__(self, key, value)
        object.__setattr__(self, "pit_cutoff_at", cutoff)
        object.__setattr__(self, "created_at", created)
        for key, value in periods.items():
            object.__setattr__(self, key, value)
        object.__setattr__(self, "manifest_hash", manifest_hash)

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


__all__ = ["DatasetManifest", "FeatureRecord", "LabelRecord"]
