"""Naive/Ridge/LightGBM/XGBoost를 동일한 expected-return 계약으로 비교한다."""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol, Sequence

import numpy as np

from investment_agent.platform.serialization import canonical_json, parse_datetime
from investment_agent.research.evaluation.alpha import average_ranks

_MODELS = {"naive", "ridge", "lightgbm", "xgboost"}


class ExpectedReturnModel(Protocol):
    def predict(self, features: np.ndarray) -> np.ndarray: ...


@dataclass(frozen=True)
class BaselineEvaluation:
    rmse: float
    mae: float
    direction_accuracy: float
    rank_correlation: float
    sample_count: int


@dataclass(frozen=True)
class ModelArtifact:
    """모델 이름 대신 dataset·code·parameter hash로 재현성을 증명한다."""

    artifact_id: str
    model_kind: str
    horizon_days: int
    train_period: tuple[str, str]
    validation_period: tuple[str, str]
    oos_period: tuple[str, str]
    parameters: Mapping[str, Any]
    random_seed: int
    dataset_hash: str
    code_version: str
    artifact_hash: str
    validation: BaselineEvaluation
    out_of_sample: BaselineEvaluation

    def to_record(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "parameters": dict(self.parameters),
            "validation": asdict(self.validation),
            "out_of_sample": asdict(self.out_of_sample),
        }

    def to_db_record(
        self,
        *,
        artifact_uri: str,
        code_commit: str | None = None,
    ) -> dict[str, Any]:
        """공통 trading.model_versions 원장에 바로 저장할 행을 만든다."""
        if not str(artifact_uri).strip():
            raise ValueError("artifact_uri is required")
        return {
            "artifact_id": self.artifact_id,
            "algorithm": self.model_kind,
            "train_start": self.train_period[0],
            "train_end": self.train_period[1],
            "seed": self.random_seed,
            "artifact_uri": str(artifact_uri),
            "sha256": self.artifact_hash,
            "params": {
                "horizon_days": self.horizon_days,
                "parameters": dict(self.parameters),
                "validation_period": list(self.validation_period),
                "oos_period": list(self.oos_period),
                "dataset_hash": self.dataset_hash,
                "code_version": self.code_version,
                "validation": asdict(self.validation),
                "out_of_sample": asdict(self.out_of_sample),
            },
            "code_commit": code_commit,
        }


class _NaiveModel:
    def __init__(self, mean: float):
        self.mean = float(mean)

    def predict(self, features: np.ndarray) -> np.ndarray:
        return np.full(len(features), self.mean, dtype=float)

    def state(self) -> dict[str, Any]:
        return {"mean": self.mean}


class _RidgeModel:
    def __init__(self, coefficients: np.ndarray, intercept: float):
        self.coefficients = np.asarray(coefficients, dtype=float)
        self.intercept = float(intercept)

    def predict(self, features: np.ndarray) -> np.ndarray:
        return np.asarray(features, dtype=float) @ self.coefficients + self.intercept

    def state(self) -> dict[str, Any]:
        return {"coefficients": self.coefficients.tolist(), "intercept": self.intercept}


class _LightGBMModel:
    """학습한 booster를 텍스트로 남긴다 — 중요도 목록만 남기면 같은 예측을 다시 만들 수 없다."""

    def __init__(self, estimator: Any):
        self.estimator = estimator

    def predict(self, features: np.ndarray) -> np.ndarray:
        return np.asarray(self.estimator.predict(np.asarray(features, dtype=float)), dtype=float)

    def state(self) -> dict[str, Any]:
        booster = self.estimator.booster_
        return {
            "booster_format": "lightgbm_model_string",
            "booster": booster.model_to_string(),
            "feature_importances": self.estimator.feature_importances_.tolist(),
        }


class _XGBoostModel:
    def __init__(self, estimator: Any):
        self.estimator = estimator

    def predict(self, features: np.ndarray) -> np.ndarray:
        return np.asarray(self.estimator.predict(np.asarray(features, dtype=float)), dtype=float)

    def state(self) -> dict[str, Any]:
        raw = self.estimator.get_booster().save_raw(raw_format="json")
        return {
            "booster_format": "xgboost_json",
            "booster": bytes(raw).decode("utf-8"),
            "feature_importances": self.estimator.feature_importances_.tolist(),
        }


def _period(value: Sequence[str], name: str) -> tuple[str, str]:
    if len(value) != 2:
        raise ValueError(f"{name} requires start and end")
    start, end = (parse_datetime(str(item)).isoformat() for item in value)
    if parse_datetime(end) <= parse_datetime(start):
        raise ValueError(f"{name} end must be after start")
    return start, end


def _rank_correlation(actual: np.ndarray, predicted: np.ndarray) -> float:
    """동점은 평균 순위로 둔다 — 상수 예측(naive)의 상관은 0이지 표본 행 순서가 아니다.

    argsort를 두 번 하면 동점이 입력 순서대로 서로 다른 순위를 받아 아래 std 가드에
    도달하지 못한다. 그러면 train 평균만 내놓는 naive baseline의 순위 상관이 표본
    정렬에 따라 ±1까지 나오고, 그 값이 challenger 비교의 기준선이 된다.
    """
    if len(actual) < 2:
        return 0.0
    a = average_ranks(np.asarray(actual, dtype=float))
    p = average_ranks(np.asarray(predicted, dtype=float))
    if np.std(a) == 0 or np.std(p) == 0:
        return 0.0
    return float(np.corrcoef(a, p)[0, 1])


def _evaluate(actual: np.ndarray, predicted: np.ndarray) -> BaselineEvaluation:
    residual = predicted - actual
    return BaselineEvaluation(
        rmse=float(np.sqrt(np.mean(residual ** 2))),
        mae=float(np.mean(np.abs(residual))),
        direction_accuracy=float(np.mean(np.sign(predicted) == np.sign(actual))),
        rank_correlation=_rank_correlation(actual, predicted),
        sample_count=int(len(actual)),
    )


def _dataset_hash(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        contiguous = np.ascontiguousarray(array)
        digest.update(str(contiguous.dtype).encode())
        digest.update(canonical_json(list(contiguous.shape)).encode())
        digest.update(contiguous.tobytes())
    return digest.hexdigest()


def _validate_xy(features: Any, labels: Any, name: str) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(features, dtype=float)
    y = np.asarray(labels, dtype=float).reshape(-1)
    if x.ndim != 2 or len(x) != len(y) or len(y) == 0:
        raise ValueError(f"{name} features/labels have incompatible shapes")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError(f"{name} contains non-finite values")
    return x, y


def fit_baseline(
    model_kind: str,
    *,
    train_features: Any,
    train_labels: Any,
    validation_features: Any,
    validation_labels: Any,
    oos_features: Any,
    oos_labels: Any,
    horizon_days: int = 5,
    train_period: Sequence[str],
    validation_period: Sequence[str],
    oos_period: Sequence[str],
    parameters: Mapping[str, Any] | None = None,
    random_seed: int = 7,
    code_version: str = "investment-agent-ml-v1",
) -> tuple[ExpectedReturnModel, ModelArtifact]:
    """시계열 split은 호출자가 만들고 이 함수는 섞지 않은 세 구간만 학습·평가한다."""
    kind = str(model_kind).lower().strip()
    if kind not in _MODELS:
        raise ValueError(f"unsupported baseline: {kind}")
    if horizon_days not in {1, 5, 20, 63}:
        raise ValueError("horizon_days must be 1, 5, 20, or 63")
    if isinstance(random_seed, bool) or not 0 <= int(random_seed) < 2**32:
        raise ValueError("random_seed must be a uint32")
    random.seed(random_seed)
    np.random.seed(random_seed)
    train_x, train_y = _validate_xy(train_features, train_labels, "train")
    val_x, val_y = _validate_xy(validation_features, validation_labels, "validation")
    oos_x, oos_y = _validate_xy(oos_features, oos_labels, "oos")
    if val_x.shape[1] != train_x.shape[1] or oos_x.shape[1] != train_x.shape[1]:
        raise ValueError("all splits must share feature columns")
    params = dict(parameters or {})
    if kind == "naive":
        model: Any = _NaiveModel(float(np.mean(train_y)))
    elif kind == "ridge":
        alpha = float(params.get("alpha", 1.0))
        if not math.isfinite(alpha) or alpha <= 0:
            raise ValueError("ridge alpha must be positive")
        # 규제항은 계수 크기에 벌점을 주므로 단위가 큰 feature(시가총액 log, RSI)가
        # 단위가 작은 feature(수익률)보다 덜 깎인다. train 구간 통계로만 z-score해
        # 벌점을 공정하게 만들고, 해를 원 단위 계수로 되돌려 저장한다 — 그래서
        # 추론 쪽(`ml_inference`)은 scaler 없이 같은 `x @ coefficients + intercept`를 쓴다.
        means = train_x.mean(axis=0)
        scales = train_x.std(axis=0)
        scales = np.where(scales > 1e-12, scales, 1.0)
        standardized_x = (train_x - means) / scales
        target_mean = float(train_y.mean())
        centered_y = train_y - target_mean
        gram = standardized_x.T @ standardized_x + alpha * np.eye(train_x.shape[1])
        coefficients = np.linalg.solve(gram, standardized_x.T @ centered_y) / scales
        model = _RidgeModel(coefficients, target_mean - float(means @ coefficients))
        params["alpha"] = alpha
        params["feature_scaling"] = "train_zscore"
    elif kind == "lightgbm":
        try:
            from lightgbm import LGBMRegressor
        except ImportError as exc:  # pragma: no cover - 선택 의존성
            raise RuntimeError("LightGBM이 필요하다: uv sync --group ml") from exc
        # 단일 스레드·deterministic으로 학습해야 같은 dataset이 같은 booster 문자열(= 같은 artifact
        # hash)을 낸다. 병렬 학습은 부동소수 합산 순서가 달라 재현이 깨진다.
        params = {"n_jobs": 1, "deterministic": True, "force_row_wise": True, **params}
        model = _LightGBMModel(LGBMRegressor(random_state=random_seed, verbosity=-1, **params).fit(train_x, train_y))
    else:
        try:
            from xgboost import XGBRegressor
        except ImportError as exc:  # pragma: no cover - 선택 의존성
            raise RuntimeError("XGBoost가 필요하다: uv sync --group ml") from exc
        model = _XGBoostModel(XGBRegressor(random_state=random_seed, n_jobs=1, **params).fit(train_x, train_y))

    state = model.state()
    dataset_hash = _dataset_hash(train_x, train_y, val_x, val_y, oos_x, oos_y)
    identity = {
        "model_kind": kind,
        "horizon_days": horizon_days,
        "parameters": params,
        "random_seed": random_seed,
        "dataset_hash": dataset_hash,
        "code_version": code_version,
        "state": state,
    }
    artifact_hash = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    artifact = ModelArtifact(
        artifact_id=f"model_{artifact_hash[:24]}",
        model_kind=kind,
        horizon_days=horizon_days,
        train_period=_period(train_period, "train_period"),
        validation_period=_period(validation_period, "validation_period"),
        oos_period=_period(oos_period, "oos_period"),
        parameters=params,
        random_seed=random_seed,
        dataset_hash=dataset_hash,
        code_version=code_version,
        artifact_hash=artifact_hash,
        validation=_evaluate(val_y, np.asarray(model.predict(val_x), dtype=float)),
        out_of_sample=_evaluate(oos_y, np.asarray(model.predict(oos_x), dtype=float)),
    )
    # JSON 직렬화가 깨지는 parameter를 artifact 원장에 넣지 않는다.
    json.loads(canonical_json(artifact.to_record()))
    return model, artifact


__all__ = ["BaselineEvaluation", "ExpectedReturnModel", "ModelArtifact", "fit_baseline"]
