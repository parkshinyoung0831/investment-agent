"""저장된 ML artifact를 오늘의 feature에 적용해 수치 예측을 만든다.

`fit_baseline`이 학습만 하고 끝나면 모델은 파일로만 남는다. 이 모듈이 그 artifact를
다시 세우고, **측정된 OOS 성능을 confidence로 환산**한다. 판단 경로에서 LLM 의견과 섞는
일은 `ml_serving`이 한다. naive·ridge는 계수로, LightGBM·XGBoost는 저장한 booster 원문으로 복원한다.

confidence를 상수로 두지 않는 것이 핵심이다. 순위 상관이 0에 가까운 모델은 낮은
가중치로 합쳐져야 하고, 그 판단 근거는 사람이 정한 숫자가 아니라 OOS 실측이어야 한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from investment_agent.trading.contracts import ContractError

# artifact 상태만으로 같은 예측을 다시 만들 수 있는 모델. 부스팅은 booster 원문을 저장한다.
RELOADABLE_KINDS = ("naive", "ridge", "lightgbm", "xgboost")
# 평균 IC가 우연이 아니라고 볼 최소 t-통계량.
MIN_IC_T_STAT = 2.0


@dataclass(frozen=True)
class LoadedModel:
    """artifact 상태에서 복원한 예측기와 그 신뢰도 근거다."""

    model_kind: str
    feature_version: str
    feature_names: tuple[str, ...]
    horizon_days: int
    artifact_id: str
    coefficients: np.ndarray | None
    intercept: float
    mean: float
    rank_correlation: float
    direction_accuracy: float
    # 학습 때 기록한 OOS 날짜별 단면 IC 요약(`evaluation.alpha`). 없으면 None.
    oos_alpha: Mapping[str, Any] | None = None
    # 부스팅 계열의 복원된 booster. 선형·상수 모델은 None.
    booster: Any = None

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        values = np.asarray(matrix, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != len(self.feature_names):
            raise ContractError("inference matrix does not match the trained feature axis")
        if not np.isfinite(values).all():
            raise ContractError("inference matrix must be finite; impute before predicting")
        if self.model_kind == "naive":
            return np.full(len(values), self.mean, dtype=np.float64)
        if self.model_kind == "lightgbm":
            return np.asarray(self.booster.predict(values), dtype=np.float64)
        if self.model_kind == "xgboost":
            import xgboost

            return np.asarray(self.booster.predict(xgboost.DMatrix(values)), dtype=np.float64)
        assert self.coefficients is not None
        return values @ self.coefficients + self.intercept

    @property
    def confidence(self) -> float:
        """OOS 순위 능력을 0~1 신뢰도로 옮긴다.

        날짜별 단면 IC가 기록돼 있으면 그것을 쓴다. 날짜를 섞은 순위 상관은 시장 전체의
        공통 움직임을 순위 능력으로 착각하기 때문이다. 평균 IC가 통계적으로 0과 구별되지
        않으면(t < 2) 신뢰도는 0이다. 일별 주식 단면에서 IC 0.05면 강한 편이라 10배로
        옮기고, 단일 모델이 LLM 의견을 압도하지 못하게 0.8에서 자른다. 음의 상관은 신호가
        아니라 잡음이므로 0으로 깎는다.
        """
        if self.oos_alpha:
            mean_ic = float(self.oos_alpha.get("mean_ic") or 0.0)
            t_stat = float(self.oos_alpha.get("ic_t_stat") or 0.0)
            if not math.isfinite(mean_ic) or not math.isfinite(t_stat) or t_stat < MIN_IC_T_STAT:
                return 0.0
            return float(min(0.8, max(0.0, mean_ic * 10.0)))
        return float(min(0.8, max(0.0, self.rank_correlation)))

    def probability_up(self, prediction: float) -> float:
        """방향 정확도를 그대로 상승 확률로 쓴다. 근거 없는 0.5 고정을 피한다."""
        accuracy = float(min(1.0, max(0.0, self.direction_accuracy)))
        if prediction == 0.0:
            return 0.5
        return accuracy if prediction > 0 else 1.0 - accuracy


def load_model(payload: Mapping[str, Any]) -> LoadedModel:
    """`train_baseline`이 남긴 artifact JSON을 예측 가능한 형태로 되돌린다."""
    artifact = payload.get("artifact")
    state = payload.get("model_state")
    names = payload.get("feature_names")
    if not isinstance(artifact, Mapping) or not isinstance(state, Mapping):
        raise ContractError("artifact payload must carry 'artifact' and 'model_state'")
    if not isinstance(names, Sequence) or not names:
        raise ContractError("artifact payload must carry 'feature_names'")
    kind = str(artifact.get("model_kind") or "").lower()
    if kind not in RELOADABLE_KINDS:
        raise ContractError(
            f"{kind or 'unknown'} artifact does not store a reloadable model; "
            f"live inference supports {RELOADABLE_KINDS}"
        )
    horizon = int(artifact.get("horizon_days") or 0)
    if horizon <= 0:
        raise ContractError("artifact does not state its horizon")
    feature_names = tuple(str(name) for name in names)
    coefficients = None
    intercept = 0.0
    mean = 0.0
    booster = None
    if kind in ("lightgbm", "xgboost"):
        booster = _load_booster(kind, state)
    elif kind == "ridge":
        raw = state.get("coefficients")
        if not isinstance(raw, Sequence) or len(raw) != len(feature_names):
            raise ContractError("ridge coefficients do not match feature_names")
        coefficients = np.asarray([float(value) for value in raw], dtype=np.float64)
        intercept = float(state.get("intercept", 0.0))
    else:
        mean = float(state.get("mean", 0.0))
    oos = artifact.get("out_of_sample") or {}
    return LoadedModel(
        model_kind=kind,
        feature_version=str(artifact.get("feature_version") or ""),
        feature_names=feature_names,
        horizon_days=horizon,
        artifact_id=str(artifact.get("artifact_id") or "unknown"),
        coefficients=coefficients,
        intercept=intercept,
        mean=mean,
        rank_correlation=float(oos.get("rank_correlation") or 0.0),
        direction_accuracy=float(oos.get("direction_accuracy") or 0.5),
        oos_alpha=(dict(payload["out_of_sample_alpha"]) if isinstance(payload.get("out_of_sample_alpha"), Mapping) else None),
        booster=booster,
    )


def _load_booster(kind: str, state: Mapping[str, Any]) -> Any:
    """저장한 booster 원문을 되살린다. 원문이 없는 옛 artifact는 중요도만 있어 복원할 수 없다."""
    text = state.get("booster")
    if not isinstance(text, str) or not text:
        raise ContractError(f"{kind} artifact has no stored booster; retrain with the current trainer")
    try:
        if kind == "lightgbm":
            import lightgbm

            return lightgbm.Booster(model_str=text)
        import xgboost

        booster = xgboost.Booster()
        booster.load_model(bytearray(text.encode("utf-8")))
        return booster
    except ImportError as exc:
        raise ContractError(f"{kind} is not installed for inference: uv sync --group ml") from exc


__all__ = [
    "MIN_IC_T_STAT",
    "RELOADABLE_KINDS",
    "LoadedModel",
    "load_model",
]
