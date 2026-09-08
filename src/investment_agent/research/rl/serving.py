"""승격된 RL 정책을 실제 판단 시점에 불러 목표비중을 만드는 자리.

## 왜 이 파일이 생겼나

학습·평가·승격은 이미 있었는데 **추론 결과를 판단 경로로 흘려보내는 배선만 없었다.**
그래서 `portfolio_shadow`가 `SignalBlender`를 부르면서 `rl_target_weights`를 넘기지 못했고,
`blend()`는 RL 목표비중이 없으면 RL 신호를 LLM 신호로 대체하므로 **융합 결과가 입력과 같은**
상태였다. 정책을 아무리 학습·승격시켜도 배분이 바뀌지 않았다는 뜻이다.

## 기본은 꺼져 있다

`AI_INVESTOR_RL_BLEND_ENABLED`가 참일 때만 목표비중을 판단에 반영한다. 꺼져 있으면
**오늘과 완전히 같은 제안을 낸다** — 대신 "켰다면 어떻게 달라졌을지"를 계산해 기록한다.
바꾸기 전에 얼마나 달라지는지를 먼저 재기 위한 것이고, 이 비교 기록이 쌓이기 전에는
켜지 않는다. 사람이 명시적으로 켠다.

## 학습 대상은 사람의 선택이 아니라 시스템의 선택이다

사람이 실제로 무엇을 샀는지는 여기 들어오지 않는다. 사람이 고른 것만으로 학습하면 정책은
시장이 아니라 그 사람의 취향을 배우고, 거른 후보의 결과가 데이터에서 통째로 빠져 성능
추정이 실제보다 좋게 나온다. 실제 체결 기록은 비용 모델 보정과 사후 비교에만 쓴다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import parse_datetime
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL
from investment_agent.research.rl.baseline import BaselinePolicyModel, load_baseline_policy
from investment_agent.research.rl.contracts import (
    MembershipSnapshot,
    MembershipTimeline,
    RLSafetyError,
)
from investment_agent.research.rl.features import (
    FeatureSnapshot,
    FeatureSpec,
    LiveInferenceFrame,
    build_live_inference_frame,
)

log = get_logger(__name__)

# 이 플래그만이 융합을 켠다. 미설정·오타는 꺼진 것으로 읽는다(fail-closed).
BLEND_FLAG = "AI_INVESTOR_RL_BLEND_ENABLED"
_TRUE = {"1", "true", "yes", "on"}

# 추론에 쓸 feature snapshot을 얼마나 거슬러 찾을지. 하루치가 없으면 추론하지 않는다.
DEFAULT_SNAPSHOT_LOOKBACK_DAYS = 3


def blend_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """RL 목표비중을 판단에 반영할지. 기본은 꺼짐."""
    source = os.environ if environ is None else environ
    return str(source.get(BLEND_FLAG, "")).strip().lower() in _TRUE


@dataclass(frozen=True)
class RlBlendOutcome:
    """융합을 켰을 때와 껐을 때를 나란히 남긴 기록.

    `applied`가 거짓이면 제안은 오늘과 같다. 그래도 `weights`와 `deltas`는 채워 두고,
    켰다면 무엇이 달라졌을지를 로그로 남긴다.
    """

    available: bool
    applied: bool
    reason: str | None = None
    policy_artifact_id: str | None = None
    feature_version: str | None = None
    inference_input_hash: str | None = None
    membership_hash: str | None = None
    weights: dict[str, float] = field(default_factory=dict)
    baseline_expected_returns: dict[str, float] = field(default_factory=dict)
    blended_expected_returns: dict[str, float] = field(default_factory=dict)

    @property
    def changed_symbols(self) -> tuple[str, ...]:
        """융합을 켰다면 기대수익률이 달라졌을 종목."""
        return tuple(
            symbol
            for symbol, before in sorted(self.baseline_expected_returns.items())
            if symbol in self.blended_expected_returns
            and abs(self.blended_expected_returns[symbol] - before) > 1e-12
        )

    @property
    def max_abs_delta(self) -> float:
        """가장 크게 벌어진 기대수익률 차이. 0이면 융합이 아무것도 바꾸지 않는다."""
        deltas = [
            abs(self.blended_expected_returns[symbol] - before)
            for symbol, before in self.baseline_expected_returns.items()
            if symbol in self.blended_expected_returns
        ]
        return max(deltas) if deltas else 0.0

    def log_payload(self) -> dict[str, Any]:
        """운영 로그에 남길 요약. 원문 비중은 넣지 않는다 — 개수와 차이만 본다."""
        return {
            "rl_blend_available": self.available,
            "rl_blend_applied": self.applied,
            "rl_blend_reason": self.reason,
            "policy_artifact_id": self.policy_artifact_id,
            "feature_version": self.feature_version,
            "inference_input_hash": self.inference_input_hash,
            "changed_symbols": len(self.changed_symbols),
            "compared_symbols": len(self.baseline_expected_returns),
            "max_abs_return_delta": round(self.max_abs_delta, 6),
        }


def unavailable(reason: str) -> RlBlendOutcome:
    """추론할 수 없을 때의 결과. 실패가 아니라 '아직 없음'이다."""
    return RlBlendOutcome(available=False, applied=False, reason=reason)


def live_membership(symbols: Sequence[str], *, as_of_at: str, source_id: str) -> MembershipTimeline:
    """현재 tracked universe 하나만 담은 live membership.

    `members_at(purpose="live_inference")`는 `live_tracked`만 받는다 — 역사 membership을
    live 추론에 쓰면 그때는 없던 종목이 지금 후보로 섞인다.
    """
    return MembershipTimeline(
        source_kind="live_tracked",
        snapshots=(
            MembershipSnapshot(
                effective_at=parse_datetime(as_of_at).isoformat(),
                symbols=tuple(str(symbol).upper() for symbol in symbols),
                source_id=source_id,
                source_kind="live_tracked",
            ),
        ),
    )


def load_active_policy(policy_path: Path) -> BaselinePolicyModel | None:
    """승격된 baseline 정책을 읽는다. 없거나 깨졌으면 None — 판단은 계속 돌아간다."""
    path = Path(policy_path)
    if not path.exists():
        return None
    try:
        return load_baseline_policy(path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("failed to load active RL policy: %s", exc)
        return None


def build_inference_frame(
    repository: Any,
    model: BaselinePolicyModel,
    *,
    as_of_at: str | datetime,
    lookback_days: int = DEFAULT_SNAPSHOT_LOOKBACK_DAYS,
) -> LiveInferenceFrame:
    """정책이 학습된 축 그대로 최근 feature snapshot을 모아 추론 프레임을 만든다.

    종목 축은 **모델이 정한 것**을 쓴다. 지금 tracked인 종목을 그대로 넣으면 학습 때
    없던 축이 생겨 `predict_weights`가 거부한다 — 그래야 맞다.
    """
    point = parse_datetime(as_of_at)
    spec = FeatureSpec(version=model.feature_version, names=model.feature_names)
    rows = repository.rl_feature_snapshot_rows(
        model.symbols,
        start_as_of=(point - timedelta(days=lookback_days)).isoformat(),
        end_as_of=point.isoformat(),
        feature_version=model.feature_version,
    )
    if not rows:
        raise RLSafetyError("no RL feature snapshot is stored for the inference window")
    snapshots = [
        FeatureSnapshot(
            feature_version=str(row.get("feature_version") or spec.version),
            as_of_at=str(row["as_of_at"]),
            ticker=str(row["ticker"]),
            available_at=str(row["available_at"]),
            is_available=bool(row.get("is_available", False)),
            features={name: row["features"].get(name) for name in spec.names},
            source_ids=tuple(row.get("source_ids") or ()),
            provenance=dict(row.get("provenance") or {}),
        )
        for row in rows
    ]
    membership = live_membership(
        model.symbols,
        as_of_at=point.isoformat(),
        source_id=f"live_tracked:{point.date().isoformat()}",
    )
    return build_live_inference_frame(
        snapshots,
        symbols=model.symbols,
        spec=spec,
        membership=membership,
        as_of_at=point.isoformat(),
    )


def risky_target_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """현금을 뺀 종목 목표비중. `blend()`가 CASH를 스스로 걸러내지만 여기서 먼저 줄인다."""
    return {
        str(symbol).upper(): float(weight)
        for symbol, weight in weights.items()
        if str(symbol).upper() != CASH_SYMBOL
    }


def compute_rl_blend(
    repository: Any,
    *,
    as_of_at: str | datetime,
    policy_path: Path,
    enabled: bool | None = None,
    lookback_days: int = DEFAULT_SNAPSHOT_LOOKBACK_DAYS,
) -> RlBlendOutcome:
    """승격된 정책으로 목표비중을 만든다. 못 만들면 이유를 담은 결과를 돌려준다.

    어떤 실패도 예외로 올리지 않는다 — 여기서 죽으면 RL과 무관한 판단 실행까지 멈춘다.
    """
    active = blend_enabled() if enabled is None else bool(enabled)
    model = load_active_policy(policy_path)
    if model is None:
        return unavailable("no promoted RL policy artifact")
    try:
        frame = build_inference_frame(
            repository, model, as_of_at=as_of_at, lookback_days=lookback_days
        )
        weights = model.predict_weights(frame)
    except (RLSafetyError, ValueError, KeyError, TypeError) as exc:
        return unavailable(f"inference unavailable: {exc}")
    except Exception as exc:  # noqa: BLE001 - 저장소 오류가 판단을 멈추게 두지 않는다
        log.warning("RL inference failed: %s", exc)
        return unavailable(f"inference failed: {exc}")

    return RlBlendOutcome(
        available=True,
        applied=active,
        reason=None if active else f"{BLEND_FLAG} is off",
        policy_artifact_id=model.artifact_id,
        feature_version=model.feature_version,
        inference_input_hash=frame.input_hash,
        membership_hash=frame.membership_hash,
        weights=risky_target_weights(weights),
    )


def blend_proposals(
    proposals: Sequence[Any],
    *,
    blender: Any,
    dsr_probability: float,
    outcome: RlBlendOutcome,
) -> tuple[list[Any], RlBlendOutcome]:
    """융합을 제안에 반영하고, 켰을 때와 껐을 때의 비교를 함께 돌려준다.

    **`outcome.applied`가 거짓이면 결과는 융합 배선이 없던 때와 완전히 같다.** 목표비중은
    비교용으로만 한 번 더 계산한다 — 켜기 전에 얼마나 달라지는지를 먼저 재기 위해서다.
    """
    from dataclasses import replace

    llm_returns = {p.ticker: float(p.expected_return_5d or 0.0) for p in proposals}
    llm_confidences = {p.ticker: float(p.confidence or 0.5) for p in proposals}

    def run(target_weights: dict[str, float] | None) -> dict[str, Any]:
        return blender.blend(
            llm_expected_returns=llm_returns,
            llm_confidences=llm_confidences,
            rl_target_weights=target_weights,
            rl_dsr_probability=dsr_probability,
        )

    applied = run(outcome.weights if outcome.applied else None)
    counterfactual = (
        run(outcome.weights) if outcome.available and not outcome.applied else applied
    )
    updated = [
        replace(
            item,
            expected_return_5d=applied[item.ticker].expected_return,
            confidence=applied[item.ticker].confidence,
        )
        if item.ticker in applied
        else item
        for item in proposals
    ]
    compared = with_comparison(
        outcome,
        baseline=llm_returns,
        blended={key: value.expected_return for key, value in counterfactual.items()},
    )
    return updated, compared


def with_comparison(
    outcome: RlBlendOutcome,
    *,
    baseline: Mapping[str, float],
    blended: Mapping[str, float],
) -> RlBlendOutcome:
    """켰을 때와 껐을 때의 기대수익률을 붙여 비교 가능한 기록으로 만든다."""
    return RlBlendOutcome(
        available=outcome.available,
        applied=outcome.applied,
        reason=outcome.reason,
        policy_artifact_id=outcome.policy_artifact_id,
        feature_version=outcome.feature_version,
        inference_input_hash=outcome.inference_input_hash,
        membership_hash=outcome.membership_hash,
        weights=dict(outcome.weights),
        baseline_expected_returns={str(k).upper(): float(v) for k, v in baseline.items()},
        blended_expected_returns={str(k).upper(): float(v) for k, v in blended.items()},
    )


__all__ = [
    "BLEND_FLAG",
    "RlBlendOutcome",
    "blend_enabled",
    "blend_proposals",
    "build_inference_frame",
    "compute_rl_blend",
    "live_membership",
    "load_active_policy",
    "risky_target_weights",
    "unavailable",
    "with_comparison",
]
