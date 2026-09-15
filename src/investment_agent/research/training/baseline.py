"""ResearchDataset을 기존 Naive/Ridge/GBM/XGB 학습 계약에 연결한다."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from investment_agent.trading.contracts import parse_datetime
from investment_agent.research.models.baselines import ExpectedReturnModel, ModelArtifact, fit_baseline
from investment_agent.research.datasets import ResearchDataset
from investment_agent.research.evaluation.alpha import CrossSectionalAlphaScore, cross_sectional_alpha_metrics


@dataclass(frozen=True)
class BaselineTrainingResult:
    model: ExpectedReturnModel
    artifact: ModelArtifact
    train_indexes: tuple[int, ...]
    validation_indexes: tuple[int, ...]
    test_indexes: tuple[int, ...]
    # OOS 구간의 날짜별 단면 IC. 종목 수가 모자라 계산할 수 없으면 None이다.
    oos_alpha: CrossSectionalAlphaScore | None = None


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


EXCESS_LABEL_PREFIX = "excess_return_"


def label_horizon_days(label_definition: str) -> int:
    """`excess_return_20d` label 정의에서 거래일 수를 읽는다.

    ML 출력은 판단 경로에서 기대**초과**수익으로 쓰인다. 원수익률(`forward_return_*`)로 학습한 모델은
    시장 전체가 오른 구간을 종목 능력으로 배우므로 여기서 거부한다 — 거래비용은 optimizer가 따로 뺀다.
    """
    match = re.fullmatch(rf"{EXCESS_LABEL_PREFIX}(\d+)d", str(label_definition).strip())
    if match is None:
        raise ValueError(f"label must be a benchmark excess return with a horizon: {label_definition!r}")
    return int(match.group(1))


def train_baseline_dataset(
    dataset: ResearchDataset,
    *,
    model_kind: str = "ridge",
    train_split: tuple[int, int],
    validation_split: tuple[int, int],
    test_split: tuple[int, int],
    horizon_days: int | None = None,
    parameters: dict[str, Any] | None = None,
    random_seed: int = 7,
    code_version: str = "investment-agent-research-v1",
) -> BaselineTrainingResult:
    """호출자가 정한 시간 split을 섞지 않고 기존 baseline trainer를 실행한다.

    horizon은 dataset의 label 정의(`excess_return_20d`)가 정한다. 호출자가 따로 넘긴 값과
    다르면 실패한다 — 20일 label로 학습한 모델에 5일이라고 적으면 serving이 엉뚱한 기간과 합친다.
    """
    label_horizon = label_horizon_days(dataset.manifest.label_definition)
    if horizon_days is not None and horizon_days != label_horizon:
        raise ValueError(f"horizon_days {horizon_days} does not match label definition {label_horizon}d")
    horizon_days = label_horizon
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
    return BaselineTrainingResult(
        return_model, artifact, train, validation, test,
        oos_alpha=_oos_alpha(dataset, test, return_model),
    )


def _oos_alpha(
    dataset: ResearchDataset,
    test: tuple[int, ...],
    model: ExpectedReturnModel,
) -> CrossSectionalAlphaScore | None:
    """OOS 예측이 같은 날짜 안에서 종목 순위를 맞혔는지. 모델 신뢰도의 근거가 된다."""
    predicted = model.predict(dataset.features[list(test)])
    try:
        return cross_sectional_alpha_metrics(
            [dataset.rows[index].as_of_at for index in test],
            [float(dataset.targets[index]) for index in test],
            [float(value) for value in predicted],
        )
    except ValueError:
        return None


__all__ = ["BaselineTrainingResult", "train_baseline_dataset"]
