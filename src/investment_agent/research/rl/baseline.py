"""외부 RL 의존성 없이 재현 가능한 선형 challenger 정책."""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from investment_agent.trading.contracts import parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL, PortfolioProposal
from investment_agent.research.rl.environment import action_to_weights
from investment_agent.research.rl.features import HistoricalTrainingSet, LiveInferenceFrame
from investment_agent.research.rl.contracts import normalize_symbols

MODEL_FORMAT_VERSION = "linear-ridge-policy-v1"


def set_deterministic_seed(seed: int) -> np.random.Generator:
    """Python·NumPy의 seed를 함께 고정하고 지역 RNG를 반환한다."""
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer between 0 and 2**32-1")
    random.seed(seed)
    np.random.seed(seed)
    return np.random.default_rng(seed)


@dataclass(frozen=True)
class BaselinePolicyConfig:
    """학습·추론 결과를 바꾸는 선형 baseline 설정."""

    ridge_alpha: float = 1e-3
    temperature: float = 1.0
    cash_logit: float = 0.0

    def __post_init__(self) -> None:
        for name in ("ridge_alpha", "temperature", "cash_logit"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.ridge_alpha <= 0.0 or self.temperature <= 0.0:
            raise ValueError("ridge_alpha and temperature must be positive")


@dataclass(frozen=True)
class BaselinePolicyModel:
    """JSON만으로 저장 가능한 표준화 계수와 action 정책."""

    feature_version: str
    feature_names: tuple[str, ...]
    symbols: tuple[str, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    seed: int
    train_start: str
    train_end: str
    training_data_hash: str
    config: BaselinePolicyConfig = field(default_factory=BaselinePolicyConfig)
    model_hash: str = field(init=False)
    artifact_id: str = field(init=False)

    def __post_init__(self) -> None:
        set_deterministic_seed(self.seed)
        feature_names = tuple(str(name).strip() for name in self.feature_names)
        n_features = len(feature_names)
        if n_features < 1 or any(not name for name in feature_names) or len(set(feature_names)) != n_features:
            raise ValueError("feature_names must be non-empty and unique")
        symbols = normalize_symbols(self.symbols)
        if symbols != tuple(self.symbols):
            raise ValueError("model symbols must be normalized and sorted")
        if len(self.feature_means) != n_features or len(self.feature_scales) != n_features:
            raise ValueError("normalization vectors must match feature_names")
        if len(self.coefficients) != n_features:
            raise ValueError("coefficients must match feature_names")
        numeric = (*self.feature_means, *self.feature_scales, *self.coefficients, self.intercept)
        if any(not math.isfinite(float(value)) for value in numeric):
            raise ValueError("baseline model numbers must be finite")
        if any(float(value) <= 0.0 for value in self.feature_scales):
            raise ValueError("feature scales must be positive")
        if not self.feature_version:
            raise ValueError("feature_version and unique symbols are required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.training_data_hash):
            raise ValueError("training_data_hash must be a sha256 digest")
        train_start = parse_datetime(self.train_start).isoformat()
        train_end = parse_datetime(self.train_end).isoformat()
        if parse_datetime(train_end) <= parse_datetime(train_start):
            raise ValueError("train_end must be after train_start")
        object.__setattr__(self, "feature_names", feature_names)
        object.__setattr__(self, "symbols", symbols)
        object.__setattr__(self, "train_start", train_start)
        object.__setattr__(self, "train_end", train_end)
        core = self._core_payload()
        model_hash = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
        object.__setattr__(self, "model_hash", model_hash)
        object.__setattr__(self, "artifact_id", f"model_{model_hash[:24]}")

    def _core_payload(self) -> dict[str, Any]:
        return {
            "format_version": MODEL_FORMAT_VERSION,
            "feature_version": self.feature_version,
            "feature_names": list(self.feature_names),
            "symbols": list(self.symbols),
            "feature_means": list(self.feature_means),
            "feature_scales": list(self.feature_scales),
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
            "seed": self.seed,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "training_data_hash": self.training_data_hash,
            "config": asdict(self.config),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._core_payload(),
            "model_hash": self.model_hash,
            "artifact_id": self.artifact_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BaselinePolicyModel":
        expected = {
            "format_version", "feature_version", "feature_names", "symbols",
            "feature_means", "feature_scales", "coefficients", "intercept", "seed",
            "train_start", "train_end", "training_data_hash", "config", "model_hash",
            "artifact_id",
        }
        if set(payload) != expected:
            raise ValueError(
                f"baseline model field mismatch missing={sorted(expected - set(payload))} "
                f"extra={sorted(set(payload) - expected)}"
            )
        if payload["format_version"] != MODEL_FORMAT_VERSION:
            raise ValueError("unsupported baseline model format")
        config = payload["config"]
        if not isinstance(config, Mapping):
            raise ValueError("baseline config must be an object")
        model = cls(
            feature_version=str(payload["feature_version"]),
            feature_names=tuple(str(value) for value in payload["feature_names"]),
            symbols=tuple(str(value) for value in payload["symbols"]),
            feature_means=tuple(float(value) for value in payload["feature_means"]),
            feature_scales=tuple(float(value) for value in payload["feature_scales"]),
            coefficients=tuple(float(value) for value in payload["coefficients"]),
            intercept=float(payload["intercept"]),
            seed=int(payload["seed"]),
            train_start=str(payload["train_start"]),
            train_end=str(payload["train_end"]),
            training_data_hash=str(payload["training_data_hash"]),
            config=BaselinePolicyConfig(**dict(config)),
        )
        if model.model_hash != payload["model_hash"] or model.artifact_id != payload["artifact_id"]:
            raise ValueError("baseline model content hash does not match payload")
        return model

    def predict_weights(self, frame: LiveInferenceFrame) -> dict[str, float]:
        """현재 tracked mask가 false인 종목에는 반드시 0 비중을 준다."""
        if frame.feature_version != self.feature_version:
            raise ValueError("inference feature version does not match model")
        if frame.feature_names != self.feature_names or frame.symbols != self.symbols:
            raise ValueError("inference feature axes do not match model")
        logits = self.action_logits(frame.features, frame.availability)
        weights = action_to_weights(logits, frame.availability)
        return {
            **{symbol: float(weights[i]) for i, symbol in enumerate(self.symbols)},
            CASH_SYMBOL: float(weights[-1]),
        }

    def action_logits(
        self,
        features: np.ndarray,
        availability: np.ndarray,
    ) -> np.ndarray:
        """historical 평가와 live 추론이 공유하는 결정적 action logit."""
        values = np.asarray(features, dtype=np.float64)
        mask = np.asarray(availability, dtype=bool)
        if values.shape != (len(self.symbols), len(self.feature_names)):
            raise ValueError("policy feature matrix does not match model axes")
        if mask.shape != (len(self.symbols),):
            raise ValueError("policy availability mask does not match model symbols")
        if not np.isfinite(values).all():
            raise ValueError("policy features must be finite")
        means = np.asarray(self.feature_means, dtype=np.float64)
        scales = np.asarray(self.feature_scales, dtype=np.float64)
        coefficients = np.asarray(self.coefficients, dtype=np.float64)
        standardized = (values - means) / scales
        scores = standardized @ coefficients + self.intercept
        return np.concatenate((
            scores / self.config.temperature,
            np.asarray([self.config.cash_logit], dtype=np.float64),
        ))

    def infer_proposal(
        self,
        frame: LiveInferenceFrame,
        *,
        run_id: str,
        stage: str = "shadow",
    ) -> PortfolioProposal:
        """baseline을 실행 권한 없는 RL challenger PortfolioProposal로 변환한다."""
        return PortfolioProposal.create(
            run_id=run_id,
            source_type="rl",
            source_version=MODEL_FORMAT_VERSION,
            stage=stage,
            as_of_at=frame.as_of_at,
            weights=self.predict_weights(frame),
            confidence=0.5,
            reasoning=("point-in-time 선형 ridge baseline challenger 추론",),
            model_artifact_id=self.artifact_id,
            metadata={
                "coverage": "partial_universe",
                "execution_eligible": False,
                "purpose": "rl_baseline_challenger",
                "inference_input_hash": frame.input_hash,
                "membership_hash": frame.membership_hash,
            },
        )


@dataclass(frozen=True)
class DurablePolicyArtifact:
    """파일 hash와 DB model_artifacts 행을 함께 제공하는 저장 결과."""

    artifact_id: str
    artifact_uri: str
    sha256: str
    feature_version: str
    train_start: str
    train_end: str
    seed: int
    model_hash: str
    training_data_hash: str
    config: dict[str, Any]

    def to_model_artifact_row(self, *, code_commit: str | None = None) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "algorithm": "rule",
            "feature_version": self.feature_version,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "seed": self.seed,
            "artifact_uri": self.artifact_uri,
            "sha256": self.sha256,
            "params": {
                "policy_type": MODEL_FORMAT_VERSION,
                "model_hash": self.model_hash,
                "training_data_hash": self.training_data_hash,
                **self.config,
            },
            "code_commit": code_commit,
        }


def train_baseline_policy(
    training_set: HistoricalTrainingSet,
    *,
    train_range: tuple[int, int],
    seed: int,
    config: BaselinePolicyConfig | None = None,
) -> BaselinePolicyModel:
    """명시한 train window만으로 scaler와 ridge 계수를 함께 적합한다."""
    set_deterministic_seed(seed)
    start, end = train_range
    dataset = training_set.dataset
    if not 0 <= start < end <= len(dataset.as_of_values) or end - start < 2:
        raise ValueError("train_range must contain at least two in-bounds periods")
    mask = dataset.availability[start:end]
    x = dataset.features[start:end][mask]
    excess = (
        dataset.forward_returns[start:end]
        - dataset.benchmark_forward_returns[start:end, np.newaxis]
    )
    y = excess[mask]
    if len(y) < 2:
        raise ValueError("training window requires at least two available asset-period samples")
    means = np.mean(x, axis=0)
    scales = np.std(x, axis=0, ddof=0)
    scales = np.where(scales <= 1e-12, 1.0, scales)
    normalized = (x - means) / scales
    design = np.column_stack((np.ones(len(normalized)), normalized))
    selected_config = config or BaselinePolicyConfig()
    penalty = np.eye(design.shape[1], dtype=np.float64) * selected_config.ridge_alpha
    penalty[0, 0] = 0.0
    system = design.T @ design + penalty
    rhs = design.T @ y
    try:
        solved = np.linalg.solve(system, rhs)
    except np.linalg.LinAlgError:
        solved = np.linalg.pinv(system) @ rhs
    fit_identity = {
        "feature_version": dataset.feature_version,
        "symbols": dataset.symbols,
        "feature_names": dataset.feature_names,
        "as_of_values": dataset.as_of_values[start:end],
        "forward_end_values": training_set.forward_end_values[start:end],
        "features": dataset.features[start:end].tolist(),
        "forward_returns": dataset.forward_returns[start:end].tolist(),
        "benchmark_forward_returns": dataset.benchmark_forward_returns[start:end].tolist(),
        "availability": dataset.availability[start:end].tolist(),
        "membership_hash": training_set.membership_hash,
        "seed": seed,
        "config": asdict(selected_config),
    }
    training_data_hash = hashlib.sha256(
        canonical_json(fit_identity).encode("utf-8")
    ).hexdigest()
    return BaselinePolicyModel(
        feature_version=dataset.feature_version,
        feature_names=dataset.feature_names,
        symbols=dataset.symbols,
        feature_means=tuple(float(value) for value in means),
        feature_scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in solved[1:]),
        intercept=float(solved[0]),
        seed=seed,
        train_start=dataset.as_of_values[start],
        train_end=dataset.as_of_values[end - 1],
        training_data_hash=training_data_hash,
        config=selected_config,
    )


def save_baseline_policy(model: BaselinePolicyModel, path: Path) -> DurablePolicyArtifact:
    """pickle 없이 canonical JSON을 원자적으로 교체해 durable artifact로 저장한다."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    body = canonical_json(model.to_dict()) + "\n"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8", newline="\n")
    temporary.replace(destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return DurablePolicyArtifact(
        artifact_id=model.artifact_id,
        artifact_uri=str(destination),
        sha256=digest,
        feature_version=model.feature_version,
        train_start=model.train_start,
        train_end=model.train_end,
        seed=model.seed,
        model_hash=model.model_hash,
        training_data_hash=model.training_data_hash,
        config=asdict(model.config),
    )


def load_baseline_policy(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> BaselinePolicyModel:
    """파일과 내부 content hash를 모두 확인한 뒤 모델을 복원한다."""
    source = Path(path)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("baseline artifact file hash does not match expected_sha256")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("baseline artifact must contain one JSON object")
    return BaselinePolicyModel.from_dict(payload)


__all__ = [
    "BaselinePolicyConfig",
    "BaselinePolicyModel",
    "DurablePolicyArtifact",
    "load_baseline_policy",
    "save_baseline_policy",
    "set_deterministic_seed",
    "train_baseline_policy",
]
