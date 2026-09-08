"""ResearchDataset을 기존 Naive/Ridge/GBM/XGB 학습 계약에 연결한다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from investment_agent.trading.contracts import parse_datetime
from investment_agent.research.models.baselines import ExpectedReturnModel, ModelArtifact, fit_baseline
from investment_agent.research.datasets import ResearchDataset


@dataclass(frozen=True)
class BaselineTrainingResult:
    model: ExpectedReturnModel
    artifact: ModelArtifact
    train_indexes: tuple[int, ...]
    validation_indexes: tuple[int, ...]
    test_indexes: tuple[int, ...]


def _indexes(dataset: ResearchDataset, split: tuple[int, int]) -> tuple[int, ...]:
    start, end = split
    if not 0 <= start < end <= len(dataset.rows):
        raise ValueError("training split is outside dataset rows")
    return tuple(range(start, end))


def _period_for_indexes(dataset: ResearchDataset, indexes: tuple[int, ...]) -> tuple[str, str]:
    """한 행짜리 validation/OOS도 artifact 기간 계약을 만족하게 표현한다."""
    start = parse_datetime(dataset.rows[indexes[0]].as_of_at)
    end = parse_datetime(dataset.rows[indexes[-1]].as_of_at)
    if end <= start:
        end = start + timedelta(microseconds=1)
    return start.isoformat(), end.isoformat()


def train_baseline_dataset(
    dataset: ResearchDataset,
    *,
    model_kind: str = "ridge",
    train_split: tuple[int, int],
    validation_split: tuple[int, int],
    test_split: tuple[int, int],
    horizon_days: int = 5,
    parameters: dict[str, Any] | None = None,
    random_seed: int = 7,
    code_version: str = "investment-agent-research-v1",
) -> BaselineTrainingResult:
    """호출자가 정한 시간 split을 섞지 않고 기존 baseline trainer를 실행한다."""
    train = _indexes(dataset, train_split)
    validation = _indexes(dataset, validation_split)
    test = _indexes(dataset, test_split)
    if set(train) & set(validation) or set(train) & set(test) or set(validation) & set(test):
        raise ValueError("train, validation, and test splits must not overlap")
    return_model, artifact = fit_baseline(
        model_kind,
        train_features=dataset.features[list(train)],
        train_labels=dataset.targets[list(train)],
        validation_features=dataset.features[list(validation)],
        validation_labels=dataset.targets[list(validation)],
        oos_features=dataset.features[list(test)],
        oos_labels=dataset.targets[list(test)],
        feature_version=dataset.manifest.feature_version,
        horizon_days=horizon_days,
        train_period=_period_for_indexes(dataset, train),
        validation_period=_period_for_indexes(dataset, validation),
        oos_period=_period_for_indexes(dataset, test),
        parameters=parameters,
        random_seed=random_seed,
        code_version=code_version,
    )
    return BaselineTrainingResult(return_model, artifact, train, validation, test)


__all__ = ["BaselineTrainingResult", "train_baseline_dataset"]
