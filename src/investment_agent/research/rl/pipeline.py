"""baseline 정책을 purged walk-forward train/validation/test로 실행한다."""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from investment_agent.platform.serialization import canonical_json
from investment_agent.research.rl.baseline import (
    BaselinePolicyConfig,
    BaselinePolicyModel,
    DurablePolicyArtifact,
    save_baseline_policy,
    train_baseline_policy,
)
from investment_agent.research.rl.environment import FeatureDataset, RewardConfig, WeightEnvironmentCore
from investment_agent.research.rl.features import HistoricalTrainingSet
from investment_agent.research.rl.leakage import audit_walk_forward_leakage
from investment_agent.research.training.splits import WalkForwardSplit


@dataclass(frozen=True)
class PolicyEvaluation:
    """비용과 turnover를 반영한 한 validation/test window 결과."""

    periods: int
    total_reward: float
    total_return: float
    benchmark_return: float
    excess_return: float
    max_drawdown: float
    turnover: float
    transaction_cost: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WalkForwardPolicyWindow:
    """한 train/validation/test window의 모델과 독립 평가."""

    window_index: int
    split: WalkForwardSplit
    model: BaselinePolicyModel
    validation: PolicyEvaluation
    test: PolicyEvaluation
    artifact: DurablePolicyArtifact | None = None


@dataclass(frozen=True)
class WalkForwardPolicyRun:
    """입력·정책·seed가 같으면 동일한 hash를 갖는 전체 실행 결과."""

    run_hash: str
    seed: int
    data_hash: str
    windows: tuple[WalkForwardPolicyWindow, ...]


def _slice_dataset(dataset: FeatureDataset, bounds: tuple[int, int]) -> FeatureDataset:
    start, end = bounds
    if not 0 <= start < end <= len(dataset.as_of_values):
        raise ValueError("evaluation range is out of bounds")
    return FeatureDataset(
        symbols=dataset.symbols,
        feature_names=dataset.feature_names,
        as_of_values=dataset.as_of_values[start:end],
        features=dataset.features[start:end],
        forward_returns=dataset.forward_returns[start:end],
        benchmark_forward_returns=dataset.benchmark_forward_returns[start:end],
        availability=dataset.availability[start:end],
        feature_version=dataset.feature_version,
    )


def split_dataset(
    dataset: FeatureDataset,
    *,
    holdout_fraction: float = 0.3,
) -> tuple[FeatureDataset, FeatureDataset]:
    """뒤쪽 구간을 평가용으로 떼어낸다. 학습한 구간에서 채점하면 어떤 정책도 통과한다."""
    if not 0.0 < float(holdout_fraction) < 1.0:
        raise ValueError("holdout_fraction must be between 0 and 1 exclusive")
    periods = len(dataset.as_of_values)
    if periods < 2:
        raise ValueError("splitting requires at least two point-in-time periods")
    holdout_size = min(periods - 1, max(1, int(round(periods * float(holdout_fraction)))))
    boundary = periods - holdout_size
    return (
        _slice_dataset(dataset, (0, boundary)),
        _slice_dataset(dataset, (boundary, periods)),
    )


def evaluate_baseline_policy(
    model: BaselinePolicyModel,
    dataset: FeatureDataset,
    *,
    bounds: tuple[int, int],
    reward_config: RewardConfig | None = None,
) -> PolicyEvaluation:
    """미래 feature를 보지 않고 현재 index의 action만 순서대로 평가한다."""
    if (
        model.symbols != dataset.symbols
        or model.feature_names != dataset.feature_names
        or model.feature_version != dataset.feature_version
    ):
        raise ValueError("evaluation dataset axes do not match policy model")
    window = _slice_dataset(dataset, bounds)
    core = WeightEnvironmentCore(window, reward_config or RewardConfig())
    rewards: list[float] = []
    infos: list[dict[str, Any]] = []
    while core.index < len(window.as_of_values):
        action = model.action_logits(
            window.features[core.index],
            window.availability[core.index],
        )
        _, reward, _, info = core.step(action)
        rewards.append(reward)
        infos.append(info)
    benchmark_nav = math.prod(1.0 + float(value) for value in window.benchmark_forward_returns)
    total_return = core.nav - 1.0
    benchmark_return = benchmark_nav - 1.0
    return PolicyEvaluation(
        periods=len(window.as_of_values),
        total_reward=float(math.fsum(rewards)),
        total_return=float(total_return),
        benchmark_return=float(benchmark_return),
        excess_return=float(total_return - benchmark_return),
        max_drawdown=float(max((info["drawdown"] for info in infos), default=0.0)),
        turnover=float(math.fsum(info["turnover"] for info in infos)),
        transaction_cost=float(math.fsum(info["transaction_cost"] for info in infos)),
    )


def run_baseline_walk_forward(
    training_set: HistoricalTrainingSet,
    splits: tuple[WalkForwardSplit, ...],
    *,
    seed: int,
    policy_config: BaselinePolicyConfig | None = None,
    reward_config: RewardConfig | None = None,
    artifact_dir: Path | None = None,
) -> WalkForwardPolicyRun:
    """validation/test를 학습에서 격리하고 window별 artifact를 선택적으로 저장한다."""
    if not splits:
        raise ValueError("walk-forward run requires at least one split")
    report = audit_walk_forward_leakage(training_set, splits)
    report.assert_clean()
    selected_policy = policy_config or BaselinePolicyConfig()
    selected_reward = reward_config or RewardConfig()
    windows: list[WalkForwardPolicyWindow] = []
    for index, split in enumerate(splits):
        window_seed = seed + index
        if window_seed >= 2**32:
            raise ValueError("window seed exceeds uint32 range")
        model = train_baseline_policy(
            training_set,
            train_range=split.train,
            seed=window_seed,
            config=selected_policy,
        )
        validation = evaluate_baseline_policy(
            model,
            training_set.dataset,
            bounds=split.validation,
            reward_config=selected_reward,
        )
        test = evaluate_baseline_policy(
            model,
            training_set.dataset,
            bounds=split.test,
            reward_config=selected_reward,
        )
        artifact = None
        if artifact_dir is not None:
            artifact = save_baseline_policy(
                model,
                Path(artifact_dir) / f"window-{index:03d}-{model.artifact_id}.json",
            )
        windows.append(WalkForwardPolicyWindow(
            window_index=index,
            split=split,
            model=model,
            validation=validation,
            test=test,
            artifact=artifact,
        ))
    identity = {
        "data_hash": training_set.data_hash,
        "seed": seed,
        "policy_config": asdict(selected_policy),
        "reward_config": asdict(selected_reward),
        "windows": [
            {
                "split": asdict(window.split),
                "artifact_id": window.model.artifact_id,
                "validation": window.validation.to_dict(),
                "test": window.test.to_dict(),
            }
            for window in windows
        ],
    }
    run_hash = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return WalkForwardPolicyRun(
        run_hash=run_hash,
        seed=seed,
        data_hash=training_set.data_hash,
        windows=tuple(windows),
    )


__all__ = [
    "PolicyEvaluation",
    "WalkForwardPolicyRun",
    "WalkForwardPolicyWindow",
    "evaluate_baseline_policy",
    "run_baseline_walk_forward",
    "split_dataset",
]
