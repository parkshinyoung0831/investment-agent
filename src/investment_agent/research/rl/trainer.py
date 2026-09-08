"""FinRL 방식의 5개 알고리즘을 broker 의존성 없이 실행하는 SB3 어댑터.

FinRL 배포 패키지는 사용하지 않는 외부 수집·broker 패키지까지 강제로
설치한다. 이 저장소는 같은 기반 엔진인 Stable-Baselines3의 모델 클래스만 직접
호출해 데이터와 주문 경계를 지킨다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from investment_agent.platform.serialization import canonical_json
from investment_agent.research.rl.baseline import set_deterministic_seed

SUPPORTED_ALGORITHMS = ("a2c", "ddpg", "ppo", "sac", "td3")


@dataclass(frozen=True)
class TrainingArtifact:
    artifact_id: str
    algorithm: str
    feature_version: str
    train_start: str
    train_end: str
    seed: int
    model_path: str
    sha256: str
    params: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class FinRLTrainer:
    """FinRL의 A2C/DDPG/PPO/SAC/TD3 선택을 최소 SB3 런타임으로 재현한다."""

    def __init__(self, env: Any):
        self.env = env

    @staticmethod
    def _model_class(algorithm: str):
        try:
            from stable_baselines3 import A2C, DDPG, PPO, SAC, TD3
        except ImportError as exc:  # pragma: no cover - 선택 의존성 경계
            raise RuntimeError(
                "Stable-Baselines3가 필요하다: uv sync --group rl"
            ) from exc
        return {
            "a2c": A2C,
            "ddpg": DDPG,
            "ppo": PPO,
            "sac": SAC,
            "td3": TD3,
        }[algorithm]

    def train(
        self,
        algorithm: str,
        *,
        total_timesteps: int,
        seed: int,
        model_kwargs: Mapping[str, Any] | None = None,
        tensorboard_log: str | None = None,
    ):
        name = algorithm.lower()
        if name not in SUPPORTED_ALGORITHMS:
            raise ValueError(f"unsupported FinRL algorithm: {algorithm}")
        if total_timesteps < 1:
            raise ValueError("total_timesteps must be positive")
        set_deterministic_seed(seed)
        kwargs = dict(model_kwargs or {})
        forbidden = {"env", "policy", "seed", "tensorboard_log"} & set(kwargs)
        if forbidden:
            raise ValueError(
                "model_kwargs cannot override trainer-owned fields: "
                + ", ".join(sorted(forbidden))
            )
        model_class = self._model_class(name)
        model = model_class(
            "MlpPolicy",
            self.env,
            seed=seed,
            tensorboard_log=tensorboard_log,
            verbose=0,
            **kwargs,
        )
        return model.learn(
            tb_log_name=f"ai_investor_{name}",
            total_timesteps=total_timesteps,
        )

    @staticmethod
    def save_artifact(
        model: Any,
        path: Path,
        *,
        algorithm: str,
        feature_version: str,
        train_start: str,
        train_end: str,
        seed: int,
        params: Mapping[str, Any],
    ) -> TrainingArtifact:
        path.parent.mkdir(parents=True, exist_ok=True)
        model.save(str(path))
        actual = path if path.exists() else path.with_suffix(path.suffix + ".zip")
        if not actual.exists():
            actual = path.with_suffix(".zip")
        digest = hashlib.sha256(actual.read_bytes()).hexdigest()
        identity = {
            "algorithm": algorithm,
            "feature_version": feature_version,
            "train_start": train_start,
            "train_end": train_end,
            "seed": seed,
            "sha256": digest,
            "params": dict(params),
        }
        artifact_id = "model_" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24]
        return TrainingArtifact(
            artifact_id=artifact_id,
            algorithm=algorithm,
            feature_version=feature_version,
            train_start=train_start,
            train_end=train_end,
            seed=seed,
            model_path=str(actual),
            sha256=digest,
            params=dict(params),
        )
