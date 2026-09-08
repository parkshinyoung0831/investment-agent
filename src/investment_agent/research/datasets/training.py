"""누적된 outcome 기반 TrainingDataset. 운영 모델 교체는 수행하지 않는다."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from investment_agent.trading.contracts import ContractError
from investment_agent.platform.serialization import canonical_json
from investment_agent.research.datasets.contracts import TrainingSample


@dataclass(frozen=True)
class TrainingDataset:
    samples: tuple[TrainingSample, ...]
    dataset_version: str = "training-dataset-v1"
    dataset_hash: str = ""

    def __post_init__(self) -> None:
        samples = tuple(sorted(self.samples, key=lambda item: (item.as_of_at, item.ticker, item.sample_id)))
        if not samples:
            raise ContractError("training dataset requires samples")
        ids = [sample.sample_id for sample in samples]
        if len(ids) != len(set(ids)):
            raise ContractError("training dataset contains duplicate sample_id")
        version = str(self.dataset_version).strip()
        if not version:
            raise ContractError("dataset_version is required")
        payload = {
            "dataset_version": version,
            "samples": [sample.to_dict() for sample in samples],
        }
        expected_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        supplied = str(self.dataset_hash).strip()
        if supplied and supplied != expected_hash:
            raise ContractError("training dataset hash does not match samples")
        object.__setattr__(self, "samples", samples)
        object.__setattr__(self, "dataset_version", version)
        object.__setattr__(self, "dataset_hash", expected_hash)

    def to_dict(self) -> dict:
        return {
            "dataset_version": self.dataset_version,
            "dataset_hash": self.dataset_hash,
            "samples": [sample.to_dict() for sample in self.samples],
        }


def build_training_dataset(
    samples: Sequence[TrainingSample],
    *,
    dataset_version: str = "training-dataset-v1",
) -> TrainingDataset:
    """sample을 정렬·중복 검증해 재현 가능한 dataset으로 만든다."""
    return TrainingDataset(tuple(samples), dataset_version=dataset_version)


__all__ = ["TrainingDataset", "build_training_dataset"]
