"""채택된 ML 수치 모델을 판단 시점에 적용해 TradingAgents 의견과 합치는 자리.

## 왜 이 파일이 있나

학습(`train_baseline`)·재로딩(`ml_inference`)·융합(`decision.fusion`)은 따로 있었지만,
실제 분석 경로(`portfolio_shadow`)는 셋 중 아무것도 부르지 않았다. 그래서 ML이 아무리
좋아져도 비중은 LLM 의견만으로 정해졌다. 이 모듈이 그 배선이다.

## ML은 얼마나 반영되나

사람이 정한 비율이 아니다. 모델의 신뢰도는 학습 때 기록한 **OOS 날짜별 단면 IC**에서
나온다(`LoadedModel.confidence`). IC가 통계적으로 0과 구별되지 않으면 신뢰도는 0이고,
그러면 융합하지 않는다 — fusion은 신뢰도 하한(0.05)을 두므로, 증거 없는 모델도 조금은
섞이게 되기 때문이다.

## ML은 무엇을 바꾸지 않나

행동(`signal`: exit·reduce·open …)은 TradingAgents 의견을 그대로 둔다. exit는 optimizer의
강제 제약이라, 수치 모델이 청산 명령을 뒤집게 두면 위험 축소가 모델 잡음에 흔들린다.
ML은 기대수익·상승확률·신뢰도만 조정한다.

## 켜고 끄기

`active_ml_model.json`(채택한 artifact 사본)이 있을 때만 적용된다. 파일을 두는 것이
사람의 채택 행위다. `AI_INVESTOR_ML_FUSION_ENABLED=false`면 계산만 하고 반영하지 않는다.
융합된 신호는 별도 artifact ID로 기록되므로 paper/live는 그 조합을 사람이 다시 승격해야
실행된다(`construct.py`의 승격 확인).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import parse_datetime
from investment_agent.research.features.layer import impute_cross_section
from investment_agent.research.ml_inference import LoadedModel, load_model, predict_numeric
from investment_agent.research.rl.contracts import FeatureSnapshot, RLSafetyError
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.decision.contracts import AnalystSignal
from investment_agent.trading.decision.fusion import fuse_signals
from investment_agent.trading.portfolio.contracts import SecurityProposal

log = get_logger(__name__)

FUSION_FLAG = "AI_INVESTOR_ML_FUSION_ENABLED"
_FALSE = {"0", "false", "no", "off"}
DEFAULT_SNAPSHOT_LOOKBACK_DAYS = 3
# TradingAgents 의견은 사람이 읽을 수 있는 근거를 가진 1차 판단이라 조금 더 무겁게 둔다.
# 실제 반영 비중은 여기에 각 성분의 신뢰도가 곱해진 값이다.
COMPONENT_WEIGHTS = {"numeric": 0.45, "tradingagents": 0.55}


def default_active_model_path() -> Path:
    from investment_agent.platform.storage_paths import repository_root
    return repository_root() / "artifacts" / "trading" / "ml_models" / "active_ml_model.json"


def fusion_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return str(source.get(FUSION_FLAG, "")).strip().lower() not in _FALSE


@dataclass(frozen=True)
class MlFusionOutcome:
    available: bool
    applied: bool
    reason: str | None = None
    model_artifact_id: str | None = None
    model_confidence: float = 0.0
    feature_as_of_at: str | None = None
    baseline_expected_returns: dict[str, float] = field(default_factory=dict)
    fused_expected_returns: dict[str, float] = field(default_factory=dict)
    contributions: dict[str, dict[str, float]] = field(default_factory=dict)

    def log_payload(self) -> dict[str, Any]:
        deltas = [
            abs(self.fused_expected_returns[symbol] - value)
            for symbol, value in self.baseline_expected_returns.items()
            if symbol in self.fused_expected_returns
        ]
        return {
            "ml_fusion_available": self.available,
            "ml_fusion_applied": self.applied,
            "ml_fusion_reason": self.reason,
            "model_artifact_id": self.model_artifact_id,
            "model_confidence": round(self.model_confidence, 6),
            "feature_as_of_at": self.feature_as_of_at,
            "compared_symbols": len(self.baseline_expected_returns),
            "max_abs_return_delta": round(max(deltas), 6) if deltas else 0.0,
        }


def _unavailable(reason: str, **values: Any) -> MlFusionOutcome:
    return MlFusionOutcome(available=False, applied=False, reason=reason, **values)


def load_active_model(path: Path) -> LoadedModel | None:
    """채택된 artifact만 읽는다. 없거나 깨졌으면 None — 판단은 LLM 의견만으로 계속 돈다."""
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

    결측 대체는 같은 날짜 전 종목의 중앙값으로 한다(학습 dataset과 같은 규칙). 분석한
    5종목만으로 중앙값을 내면 학습 때와 다른 값이 들어가 training-serving skew가 생긴다.
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


def tradingagents_signal(proposal: SecurityProposal) -> AnalystSignal:
    """종목 의견을 fusion이 받는 desk 신호 계약으로 옮긴다."""
    direction = max(-1.0, min(1.0, 2.0 * float(proposal.probability_up) - 1.0))
    return AnalystSignal(
        ticker=proposal.ticker,
        as_of_at=parse_datetime(proposal.as_of_at).isoformat(),
        domain="tradingagents",
        direction=direction,
        score=direction,
        confidence=float(proposal.confidence),
        expected_return=float(proposal.expected_excess_return),
        reasoning=tuple(proposal.reasoning[:1]),
        evidence_ids=tuple(proposal.evidence_ids),
        model="tradingagents",
        version="security-proposal",
    )


def fuse_proposals(
    proposals: Sequence[SecurityProposal],
    predictions: Mapping[str, Any],
) -> tuple[list[SecurityProposal], dict[str, dict[str, float]]]:
    """예측이 있는 종목만 기대수익·확률·신뢰도를 융합한다. 행동은 바꾸지 않는다."""
    fused: list[SecurityProposal] = []
    contributions: dict[str, dict[str, float]] = {}
    for proposal in proposals:
        prediction = predictions.get(proposal.ticker)
        if prediction is None:
            fused.append(proposal)
            continue
        as_of = parse_datetime(proposal.as_of_at).isoformat()
        result = fuse_signals(
            ticker=proposal.ticker,
            as_of_at=as_of,
            desk_signals=(tradingagents_signal(proposal),),
            numeric_predictions=(replace(prediction, as_of_at=as_of),),
            component_weights=COMPONENT_WEIGHTS,
            version="ml-tradingagents-fusion-v1",
        )
        signal = result.signal
        expected = signal.expected_5d_return
        if proposal.signal in {"avoid", "watch", "exit"}:
            # 부정 의견의 기대수익을 수치 모델이 양수로 끌어올리지 못하게 한다.
            expected = min(0.0, expected)
        fused.append(replace(
            proposal,
            expected_excess_return=float(expected),
            probability_up=float(signal.probability_up),
            confidence=float(signal.confidence),
        ))
        contributions[proposal.ticker] = dict(result.contributions)
    return fused, contributions


def compute_ml_fusion(
    repository: Any,
    proposals: Sequence[SecurityProposal],
    *,
    as_of_at: str | datetime,
    model_path: Path,
    enabled: bool | None = None,
    lookback_days: int = DEFAULT_SNAPSHOT_LOOKBACK_DAYS,
) -> tuple[list[SecurityProposal], MlFusionOutcome]:
    """융합한 제안과 비교 기록을 돌려준다. 어떤 실패도 판단 실행을 멈추지 않는다."""
    baseline = {proposal.ticker: float(proposal.expected_excess_return) for proposal in proposals}
    if not proposals:
        return list(proposals), _unavailable("no proposals")
    model = load_active_model(model_path)
    if model is None:
        return list(proposals), _unavailable("no adopted ML model artifact")
    identity = {"model_artifact_id": model.artifact_id, "model_confidence": model.confidence}
    if model.confidence <= 0.0:
        return list(proposals), _unavailable(
            "adopted ML model has no statistically significant OOS IC", **identity,
        )
    point = parse_datetime(as_of_at)
    try:
        rows = repository.rl_feature_snapshot_rows(
            tuple(repository.current_tracked_tickers()),
            start_as_of=(point - timedelta(days=lookback_days)).isoformat(),
            end_as_of=point.isoformat(),
            feature_version=model.feature_version,
        )
        feature_as_of, snapshots = latest_cross_section(rows, as_of_at=point, lookback_days=lookback_days)
        imputed = dict(zip((item.ticker for item in snapshots), impute_cross_section(snapshots), strict=True))
        wanted = [proposal.ticker for proposal in proposals if proposal.ticker in imputed]
        if not wanted:
            return list(proposals), _unavailable("no analyzed ticker has a feature snapshot", **identity)
        predictions = predict_numeric(
            model,
            as_of_at=point.isoformat(),
            tickers=wanted,
            feature_rows=[imputed[ticker] for ticker in wanted],
            feature_version=model.feature_version,
        )
    except (ContractError, RLSafetyError, ValueError, KeyError, TypeError) as exc:
        return list(proposals), _unavailable(f"inference unavailable: {exc}", **identity)
    except Exception as exc:  # noqa: BLE001 - 저장소 오류가 LLM 판단 실행을 멈추게 두지 않는다
        log.warning("ML fusion inference failed: %s", type(exc).__name__)
        return list(proposals), _unavailable(f"inference failed: {type(exc).__name__}", **identity)

    fused, contributions = fuse_proposals(proposals, {item.ticker: item for item in predictions})
    active = fusion_enabled() if enabled is None else bool(enabled)
    outcome = MlFusionOutcome(
        available=True,
        applied=active,
        reason=None if active else f"{FUSION_FLAG} is false",
        feature_as_of_at=feature_as_of,
        baseline_expected_returns=baseline,
        fused_expected_returns={proposal.ticker: float(proposal.expected_excess_return) for proposal in fused},
        contributions=contributions,
        **identity,
    )
    return (fused if active else list(proposals)), outcome


__all__ = [
    "COMPONENT_WEIGHTS",
    "FUSION_FLAG",
    "MlFusionOutcome",
    "compute_ml_fusion",
    "default_active_model_path",
    "fuse_proposals",
    "fusion_enabled",
    "latest_cross_section",
    "load_active_model",
    "tradingagents_signal",
]
