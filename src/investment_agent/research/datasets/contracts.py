"""Feature·label·outcome provenance를 연결하는 학습 sample 계약."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from investment_agent.trading.contracts import ContractError, json_value, parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.research.contracts import FeatureRecord, LabelRecord


@dataclass(frozen=True)
class TrainingSample:
    """미래 label이 확정된 뒤에만 생성되는 immutable 학습 행."""

    sample_id: str
    ticker: str
    as_of_at: str
    label_available_at: str
    feature_version: str
    label_definition: str
    features: Mapping[str, float]
    labels: Mapping[str, float]
    provenance: Mapping[str, Any] = field(default_factory=dict)
    outcome_id: str | None = None
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        ticker = str(self.ticker).upper().strip()
        as_of = parse_datetime(self.as_of_at).isoformat()
        label_available = parse_datetime(self.label_available_at).isoformat()
        version = str(self.feature_version).strip()
        definition = str(self.label_definition).strip()
        if not ticker or not version or not definition or label_available < as_of:
            raise ContractError("training sample identity or PIT timing is invalid")
        features = self._numbers(self.features, "features", require_non_empty=True)
        labels = self._numbers(self.labels, "labels", require_non_empty=True)
        identity = {
            "ticker": ticker,
            "as_of_at": as_of,
            "label_available_at": label_available,
            "feature_version": version,
            "label_definition": definition,
            "features": features,
            "labels": labels,
            "provenance": dict(self.provenance),
            "outcome_id": self.outcome_id,
        }
        input_hash = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        sample_id = str(self.sample_id).strip() or f"sample_{input_hash[:24]}"
        object.__setattr__(self, "sample_id", sample_id)
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "as_of_at", as_of)
        object.__setattr__(self, "label_available_at", label_available)
        object.__setattr__(self, "feature_version", version)
        object.__setattr__(self, "label_definition", definition)
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "provenance", dict(self.provenance))
        object.__setattr__(self, "input_hash", input_hash)

    @staticmethod
    def _numbers(
        values: Mapping[str, Any],
        field_name: str,
        *,
        require_non_empty: bool,
    ) -> dict[str, float]:
        if not isinstance(values, Mapping) or (require_non_empty and not values):
            raise ContractError(f"{field_name} must be a non-empty mapping")
        result: dict[str, float] = {}
        for key, value in values.items():
            name = str(key).strip()
            if not name or isinstance(value, bool):
                raise ContractError(f"{field_name} contains an invalid value")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ContractError(f"{field_name}.{name} must be numeric") from exc
            if number != number or number in {float("inf"), float("-inf")}:
                raise ContractError(f"{field_name}.{name} must be finite")
            result[name] = number
        return {name: result[name] for name in sorted(result)}

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


def build_training_sample(
    feature: FeatureRecord,
    label: LabelRecord,
    *,
    outcome_id: str | None = None,
    additional_labels: Mapping[str, float] | None = None,
) -> TrainingSample:
    """동일 시점·버전의 feature/label만 학습 sample로 결합한다."""
    if feature.ticker != label.ticker or feature.as_of_at != label.as_of_at:
        raise ContractError("feature and label identity does not match")
    if feature.feature_version != label.feature_version:
        raise ContractError("feature and label version does not match")
    labels = {
        label.label_definition: label.label,
        "benchmark": label.benchmark_label,
        **dict(additional_labels or {}),
    }
    return TrainingSample(
        sample_id="",
        ticker=feature.ticker,
        as_of_at=feature.as_of_at,
        label_available_at=label.label_available_at,
        feature_version=feature.feature_version,
        label_definition=label.label_definition,
        features=feature.features,
        labels=labels,
        provenance={
            "feature_provenance": dict(feature.provenance),
            "feature_source_ids": list(feature.source_ids),
            "label_id": label.label_id,
            "forward_end_at": label.forward_end_at,
        },
        outcome_id=outcome_id,
    )


__all__ = ["TrainingSample", "build_training_sample"]
