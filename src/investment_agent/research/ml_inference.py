"""저장된 ML artifact를 오늘의 feature에 적용해 수치 예측을 만든다.

`fit_baseline`이 학습만 하고 끝나면 모델은 파일로만 남는다. 이 모듈이 그 artifact를
다시 세워 live feature에 적용하고, **측정된 OOS 성능을 confidence로 환산**해
`fusion.fuse_signals`가 LLM 의견과 합칠 수 있는 형태로 넘긴다.

confidence를 상수로 두지 않는 것이 핵심이다. 순위 상관이 0에 가까운 모델은 낮은
가중치로 합쳐져야 하고, 그 판단 근거는 사람이 정한 숫자가 아니라 OOS 실측이어야 한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.trading.decision.fusion import NumericPrediction

# fusion._desk_returns와 같은 환산비다. 5거래일 학습 모델 하나로 세 horizon을 채울 때
# 서로 다른 비율을 쓰면 desk 의견과 수치 예측이 다른 시간축에서 합쳐진다.
HORIZON_SCALE = {1: 0.25, 5: 1.0, 20: 2.5}

# 상태만으로 결정적으로 복원되는 모델. 부스팅 계열은 artifact에 재현 가능한 상태가
# 남지 않아(중요도 목록만 저장) live 경로에서 쓰지 않는다.
RELOADABLE_KINDS = ("naive", "ridge")


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

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        values = np.asarray(matrix, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != len(self.feature_names):
            raise ContractError("inference matrix does not match the trained feature axis")
        if not np.isfinite(values).all():
            raise ContractError("inference matrix must be finite; impute before predicting")
        if self.model_kind == "naive":
            return np.full(len(values), self.mean, dtype=np.float64)
        assert self.coefficients is not None
        return values @ self.coefficients + self.intercept

    @property
    def confidence(self) -> float:
        """OOS 순위 상관을 0~1 신뢰도로 옮긴다.

        음의 상관은 신호가 아니라 잡음이므로 0으로 깎는다. 상한을 0.8로 두는 것은
        단일 baseline이 LLM 의견을 완전히 압도하지 못하게 하려는 것이다.
        """
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
    horizon = int(artifact.get("horizon_days") or 5)
    if horizon not in HORIZON_SCALE:
        raise ContractError(f"unsupported artifact horizon: {horizon}")
    feature_names = tuple(str(name) for name in names)
    coefficients = None
    intercept = 0.0
    mean = 0.0
    if kind == "ridge":
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
    )


def predict_numeric(
    model: LoadedModel,
    *,
    as_of_at: str,
    tickers: Sequence[str],
    feature_rows: Sequence[Mapping[str, float]],
    feature_version: str,
    evidence_by_ticker: Mapping[str, Sequence[str]] | None = None,
) -> tuple[NumericPrediction, ...]:
    """오늘의 feature 행렬로 종목별 NumericPrediction을 만든다.

    feature version과 컬럼 순서가 학습 때와 다르면 예측하지 않고 실패한다 —
    training-serving skew는 조용히 틀린 답을 주기 때문이다.
    """
    if feature_version != model.feature_version:
        raise ContractError(
            f"feature version mismatch: model={model.feature_version} input={feature_version}"
        )
    if len(tickers) != len(feature_rows):
        raise ContractError("tickers and feature_rows must have equal length")
    if not tickers:
        return ()
    as_of = parse_datetime(as_of_at).isoformat()
    matrix = np.asarray(
        [[float(row[name]) for name in model.feature_names] for row in feature_rows],
        dtype=np.float64,
    )
    predictions = model.predict(matrix)
    scale = HORIZON_SCALE[model.horizon_days]
    evidence = evidence_by_ticker or {}
    results: list[NumericPrediction] = []
    for ticker, value in zip(tickers, predictions):
        raw = float(value)
        if not math.isfinite(raw):
            raise ContractError(f"model produced a non-finite prediction for {ticker}")
        # 학습 horizon 값을 기준으로 나머지 두 horizon을 같은 환산비로 채운다.
        base = raw / scale
        results.append(NumericPrediction(
            ticker=str(ticker).upper(),
            as_of_at=as_of,
            expected_1d_return=base * HORIZON_SCALE[1],
            expected_5d_return=base * HORIZON_SCALE[5],
            expected_20d_return=base * HORIZON_SCALE[20],
            probability_up=model.probability_up(raw),
            confidence=model.confidence,
            uncertainty=1.0 - model.confidence,
            model_id=model.artifact_id,
            version=f"{model.model_kind}-h{model.horizon_days}",
            evidence_ids=tuple(evidence.get(str(ticker).upper(), ())),
        ))
    return tuple(results)


__all__ = [
    "HORIZON_SCALE",
    "RELOADABLE_KINDS",
    "LoadedModel",
    "load_model",
    "predict_numeric",
]
