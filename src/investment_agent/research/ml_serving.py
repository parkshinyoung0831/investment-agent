"""채택된 champion ML 모델로 판단 시점의 종목별 기대초과수익을 예측한다.

## 무엇을 예측하나

`SIGNAL_HORIZON_DAYS` 거래일 동안 **SPY 대비 초과수익**이다. 학습 label도 같은 정의
(`excess_return_20d`)여야 하고, 원수익률로 학습한 모델은 여기서 쓰지 않는다. 거래비용은 빼지 않는다 —
optimizer가 비용을 따로 계산하므로 여기서 빼면 이중 차감이다.

## 누가 쓰나

ALPHA(`trading.decision.alpha`)가 factor 기대수익과 합친다. TradingAgents 의견과는 섞지 않는다 —
LLM 논지는 숫자가 놓친 위험을 말하는 자리이고, 수치 모델과 섞으면 어느 쪽 판단인지 추적할 수 없다.

## 켜고 끄기

`active_ml_model.json`(채택한 artifact 사본)이 있을 때만 예측한다. 파일을 두는 것이 사람의 채택
행위다(`research.commands.adopt_ml_model`). challenger 학습은 이 파일을 건드리지 않는다. OOS IC가
통계적으로 0과 구별되지 않으면 신뢰도가 0이라 예측을 쓰지 않는다.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import ContractError, parse_datetime
from investment_agent.research.features.layer import impute_cross_section
from investment_agent.research.ml_inference import LoadedModel, load_model
from investment_agent.research.rl.contracts import FeatureSnapshot, RLSafetyError
from investment_agent.research.storage.repository import ResearchStore
from investment_agent.forecasting import SIGNAL_HORIZON_DAYS

log = get_logger(__name__)

DEFAULT_SNAPSHOT_LOOKBACK_DAYS = 3


def default_active_model_path() -> Path:
    from investment_agent.platform.storage_paths import repository_root
    return repository_root() / "artifacts" / "trading" / "ml_models" / "active_ml_model.json"


@dataclass(frozen=True)
class ChampionForecast:
    """champion 모델 한 번의 예측. 쓸 수 없으면 `expected_excess_returns`가 비고 이유가 남는다."""

    reason: str | None = None
    model_artifact_id: str | None = None
    # OOS 날짜별 단면 IC로 잰 신뢰도(0~0.8). ALPHA에서 ML 몫이 된다.
    confidence: float = 0.0
    feature_as_of_at: str | None = None
    expected_excess_returns: Mapping[str, float] = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        return bool(self.expected_excess_returns) and self.confidence > 0.0

    def to_metadata(self) -> dict[str, Any]:
        return {
            "is_available": self.is_available,
            "reason": self.reason,
            "model_artifact_id": self.model_artifact_id,
            "confidence": round(self.confidence, 6),
            "feature_as_of_at": self.feature_as_of_at,
            "predicted_symbols": len(self.expected_excess_returns),
        }


NO_FORECAST = ChampionForecast(reason="ml disabled")


def load_active_model(path: Path) -> LoadedModel | None:
    """채택된 artifact만 읽는다. 없거나 깨졌으면 None — ALPHA는 factor만으로 계속 돈다."""
    target = Path(path)
    if not target.exists():
        return None
    try:
        return load_model(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError, ContractError) as exc:
        log.warning("failed to load active ML model: %s", exc)
        return None


def latest_cross_section(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of_at: datetime,
    lookback_days: int,
) -> tuple[str, list[FeatureSnapshot]]:
    """판단 시점 이전에 공개된 가장 최근 **한 날짜**의 전 종목 snapshot을 고른다.

    결측 대체는 같은 날짜 전 종목의 중앙값으로 한다(학습 dataset과 같은 규칙). 예측할 종목만으로
    중앙값을 내면 학습 때와 다른 값이 들어가 training-serving skew가 생긴다.
    """
    floor = as_of_at - timedelta(days=lookback_days)
    usable = [
        row for row in rows
        if floor <= parse_datetime(str(row["as_of_at"])) <= as_of_at
        and parse_datetime(str(row["available_at"])) <= as_of_at
    ]
    if not usable:
        raise ContractError("no feature snapshot is available for the ML inference window")
    latest = max(usable, key=lambda row: parse_datetime(str(row["as_of_at"])))["as_of_at"]
    latest_point = parse_datetime(str(latest))
    snapshots = [
        FeatureSnapshot(
            feature_version=str(row["feature_version"]),
            as_of_at=str(row["as_of_at"]),
            ticker=str(row["ticker"]).upper(),
            available_at=str(row["available_at"]),
            is_available=bool(row.get("is_available", True)),
            features=dict(row["features"]),
            source_ids=tuple(row.get("source_ids") or ()),
            provenance=dict(row.get("provenance") or {}),
        )
        for row in usable
        if parse_datetime(str(row["as_of_at"])) == latest_point
    ]
    return latest_point.isoformat(), sorted(snapshots, key=lambda item: item.ticker)


def champion_forecast(
    repository: Any,
    tickers: Sequence[str],
    *,
    as_of_at: str | datetime,
    model_path: Path | None = None,
    lookback_days: int = DEFAULT_SNAPSHOT_LOOKBACK_DAYS,
    store: Any | None = None,
) -> ChampionForecast:
    """채택된 모델의 종목별 기대초과수익. 어떤 실패도 System 목표 생성을 멈추지 않는다."""
    wanted_tickers = sorted({str(ticker).upper() for ticker in tickers})
    if not wanted_tickers:
        return ChampionForecast(reason="no tickers")
    model = load_active_model(model_path or default_active_model_path())
    if model is None:
        return ChampionForecast(reason="no adopted ML model artifact")
    identity = {"model_artifact_id": model.artifact_id, "confidence": model.confidence}
    if not model.predicts_excess_return:
        return ChampionForecast(reason=f"model label is not a benchmark excess return: {model.label_definition or 'unknown'}",
                                **identity)
    if model.confidence <= 0.0:
        return ChampionForecast(reason="adopted ML model has no statistically significant OOS IC", **identity)
    if model.horizon_days != SIGNAL_HORIZON_DAYS:
        return ChampionForecast(
            reason=f"model horizon {model.horizon_days}d does not match the signal horizon {SIGNAL_HORIZON_DAYS}d",
            **identity,
        )
    point = parse_datetime(as_of_at)
    try:
        selected_store = store if store is not None else ResearchStore(read_only=True)
        rows = selected_store.rl_feature_snapshot_rows(
            tuple(repository.current_tracked_tickers()),
            start_as_of=(point - timedelta(days=lookback_days)).isoformat(),
            end_as_of=point.isoformat(),
            feature_version=model.feature_version,
        )
        feature_as_of, snapshots = latest_cross_section(rows, as_of_at=point, lookback_days=lookback_days)
        imputed = dict(zip((item.ticker for item in snapshots), impute_cross_section(snapshots), strict=True))
        wanted = [ticker for ticker in wanted_tickers if ticker in imputed]
        if not wanted:
            return ChampionForecast(reason="no requested ticker has a feature snapshot", **identity)
        if any(snapshot.feature_version != model.feature_version for snapshot in snapshots):
            raise ContractError("feature version mismatch between snapshots and the model")
        matrix = [[float(imputed[ticker][name]) for name in model.feature_names] for ticker in wanted]
        raw = model.predict(np.asarray(matrix, dtype=float))
        predictions: dict[str, float] = {}
        for ticker, value in zip(wanted, raw):
            if not math.isfinite(float(value)):
                raise ContractError(f"model produced a non-finite prediction for {ticker}")
            predictions[ticker] = float(value)
    except (ContractError, RLSafetyError, ValueError, KeyError, TypeError) as exc:
        return ChampionForecast(reason=f"inference unavailable: {exc}", **identity)
    except Exception as exc:  # noqa: BLE001 - 저장소 오류가 System 목표 생성을 멈추게 두지 않는다
        log.warning("champion ML inference failed: %s", type(exc).__name__)
        return ChampionForecast(reason=f"inference failed: {type(exc).__name__}", **identity)
    return ChampionForecast(feature_as_of_at=feature_as_of, expected_excess_returns=predictions, **identity)


__all__ = [
    "ChampionForecast",
    "NO_FORECAST",
    "champion_forecast",
    "default_active_model_path",
    "latest_cross_section",
    "load_active_model",
]
