"""PPO를 대표 RL baseline으로 학습하고 ML baseline보다 나쁘면 research로 고정한다."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from investment_agent.platform.serialization import canonical_json
from investment_agent.research.rl.environment import FeatureDataset, RewardConfig, WeightEnvironmentCore, make_gym_environment
from investment_agent.research.rl.trainer import FinRLTrainer, TrainingArtifact


@dataclass(frozen=True)
class RLPolicyEvaluation:
    periods: int
    total_return: float
    benchmark_return: float
    excess_return: float
    max_drawdown: float
    turnover: float
    transaction_cost: float


@dataclass(frozen=True)
class PPOExperimentResult:
    experiment_hash: str
    artifact: TrainingArtifact
    evaluation: RLPolicyEvaluation
    ml_baseline_excess_return: float
    beats_ml_baseline: bool
    lifecycle_status: str


def _evaluate(model: Any, dataset: FeatureDataset, reward: RewardConfig) -> RLPolicyEvaluation:
    core = WeightEnvironmentCore(dataset, reward)
    benchmark_nav = 1.0
    drawdown = 0.0
    turnover = 0.0
    cost = 0.0
    while core.index < len(dataset.as_of_values):
        observation = core.observation()
        action, _ = model.predict(observation, deterministic=True)
        _, _, _, info = core.step(action)
        benchmark_nav *= 1.0 + float(info["benchmark_return"])
        drawdown = max(drawdown, float(info["drawdown"]))
        turnover += float(info["turnover"])
        cost += float(info["transaction_cost"])
    total_return = core.nav - 1.0
    benchmark_return = benchmark_nav - 1.0
    return RLPolicyEvaluation(
        periods=len(dataset.as_of_values), total_return=total_return,
        benchmark_return=benchmark_return, excess_return=total_return - benchmark_return,
        max_drawdown=-drawdown, turnover=turnover, transaction_cost=cost,
    )


def run_ppo_experiment(
    *,
    training_dataset: FeatureDataset,
    oos_dataset: FeatureDataset,
    ml_baseline_excess_return: float,
    artifact_path: Path,
    total_timesteps: int = 10_000,
    seed: int = 7,
    model_kwargs: Mapping[str, Any] | None = None,
    reward_config: RewardConfig | None = None,
) -> PPOExperimentResult:
    if training_dataset.feature_version != oos_dataset.feature_version:
        raise ValueError("training and OOS feature versions differ")
    reward = reward_config or RewardConfig()
    trainer = FinRLTrainer(make_gym_environment(training_dataset, reward))
    model = trainer.train(
        "ppo", total_timesteps=total_timesteps, seed=seed,
        model_kwargs=model_kwargs,
    )
    params = {"total_timesteps": total_timesteps, **dict(model_kwargs or {})}
    artifact = trainer.save_artifact(
        model, artifact_path, algorithm="ppo",
        feature_version=training_dataset.feature_version,
        train_start=training_dataset.as_of_values[0],
        train_end=training_dataset.as_of_values[-1],
        seed=seed, params=params,
    )
    evaluation = _evaluate(model, oos_dataset, reward)
    beats = evaluation.excess_return > float(ml_baseline_excess_return)
    identity = {
        "artifact": artifact.to_dict(), "evaluation": asdict(evaluation),
        "ml_baseline_excess_return": ml_baseline_excess_return,
        "reward": asdict(reward),
    }
    experiment_hash = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return PPOExperimentResult(
        experiment_hash=experiment_hash, artifact=artifact, evaluation=evaluation,
        ml_baseline_excess_return=float(ml_baseline_excess_return),
        beats_ml_baseline=beats,
        lifecycle_status="challenger" if beats else "research_only",
    )


__all__ = ["PPOExperimentResult", "RLPolicyEvaluation", "run_ppo_experiment"]
