"""승격된 RL 정책으로 목표비중을 만드는 자리.

## RL은 기대수익을 고치지 않는다

RL 목표비중을 "평균보다 얼마나 더 담았나 × 배율"로 바꿔 LLM 기대수익에 섞으면, 경제적 근거가
없는 숫자가 optimizer 목적함수에 들어간다. 비중은 수익 예측이 아니라 이미 위험·비용을 풀고 난
결과라서, 그것을 다시 기대수익으로 되돌리면 같은 위험을 두 번 세게 된다. 그래서 RL은 판단
경로의 신호를 바꾸지 않는다. 승격된 정책의 목표비중은 **별도 포트폴리오 후보(challenger)**로만
계산해 기록하고, 같은 기간·같은 비용 가정의 champion과 성과로 비교한다.

## 학습 대상은 사람의 선택이 아니라 시스템의 선택이다

사람이 실제로 무엇을 샀는지는 여기 들어오지 않는다. 사람이 고른 것만으로 학습하면 정책은
시장이 아니라 그 사람의 취향을 배우고, 거른 후보의 결과가 데이터에서 통째로 빠져 성능
추정이 실제보다 좋게 나온다. 실제 체결 기록은 비용 모델 보정과 사후 비교에만 쓴다.
"""
from __future__ import annotations

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

# 추론에 쓸 feature snapshot을 얼마나 거슬러 찾을지. 하루치가 없으면 추론하지 않는다.
DEFAULT_SNAPSHOT_LOOKBACK_DAYS = 3


def default_active_policy_path() -> Path:
    """명시적으로 채택한 정책만 읽는 경로."""
    from investment_agent.platform.storage_paths import repository_root
    return repository_root() / "artifacts" / "trading" / "rl_policies" / "active_policy.json"


@dataclass(frozen=True)
class RlPolicyOutcome:
    """승격된 정책이 이번 판단 시점에 낸 목표비중과 그 재현 근거."""

    available: bool
    reason: str | None = None
    policy_artifact_id: str | None = None
    feature_version: str | None = None
    inference_input_hash: str | None = None
    membership_hash: str | None = None
    dsr_probability: float = 0.0
    weights: dict[str, float] = field(default_factory=dict)

    def log_payload(self) -> dict[str, Any]:
        """운영 로그에 남길 요약. 원문 비중은 넣지 않는다."""
        return {
            "rl_policy_available": self.available,
            "rl_policy_reason": self.reason,
            "policy_artifact_id": self.policy_artifact_id,
            "feature_version": self.feature_version,
            "inference_input_hash": self.inference_input_hash,
            "weighted_symbols": sum(1 for weight in self.weights.values() if weight > 0.0),
        }


def unavailable(reason: str) -> RlPolicyOutcome:
    """추론할 수 없을 때의 결과. 실패가 아니라 '아직 없음'이다."""
    return RlPolicyOutcome(available=False, reason=reason)


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
        import json
        from investment_agent.research.rl.bundle import load_policy_bundle
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") == "ppo-policy-v1":
            return load_policy_bundle(path)
        return load_baseline_policy(path)
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
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
    rows = [row for row in rows if (point - timedelta(days=lookback_days)) <= parse_datetime(row["as_of_at"]) <= point]
    if not rows:
        raise RLSafetyError("RL feature snapshots are stale")
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
    """현금을 뺀 종목 목표비중."""
    return {
        str(symbol).upper(): float(weight)
        for symbol, weight in weights.items()
        if str(symbol).upper() != CASH_SYMBOL
    }


def compute_rl_target_weights(
    repository: Any,
    *,
    as_of_at: str | datetime,
    policy_path: Path,
    proposals: Sequence[Any] = (),
    current_weights: Mapping[str, float] | None = None,
    lookback_days: int = DEFAULT_SNAPSHOT_LOOKBACK_DAYS,
) -> RlPolicyOutcome:
    """승격된 정책으로 목표비중을 만든다. 못 만들면 이유를 담은 결과를 돌려준다.

    어떤 실패도 예외로 올리지 않는다 — 여기서 죽으면 RL과 무관한 판단 실행까지 멈춘다.
    """
    model = load_active_policy(policy_path)
    if model is None:
        return unavailable("no promoted RL policy artifact")
    try:
        from investment_agent.research.rl.bundle import PPOPolicy
        if isinstance(model, PPOPolicy):
            trained_at = parse_datetime(model.metadata["training"]["as_of_at"])
            age = parse_datetime(as_of_at) - trained_at
            if age < timedelta(0) or age > timedelta(days=90):
                raise RLSafetyError("policy training timestamp is future or stale")
        from investment_agent.research.rl.decision_dataset import FEATURE_VERSION, decision_inference_frame
        frame = (decision_inference_frame(model, proposals, as_of_at=as_of_at)
                 if model.feature_version == FEATURE_VERSION else build_inference_frame(
                     repository, model, as_of_at=as_of_at, lookback_days=lookback_days))
        from investment_agent.research.rl.bundle import PPOPolicy
        weights = (model.predict_weights(frame, current_weights=current_weights)
                   if isinstance(model, PPOPolicy) else model.predict_weights(frame))
    except (RLSafetyError, ValueError, KeyError, TypeError) as exc:
        return unavailable(f"inference unavailable: {exc}")
    except Exception as exc:  # noqa: BLE001 - 저장소 오류가 판단을 멈추게 두지 않는다
        log.warning("RL inference failed: %s", exc)
        return unavailable(f"inference failed: {exc}")

    return RlPolicyOutcome(
        available=True,
        policy_artifact_id=model.artifact_id,
        feature_version=model.feature_version,
        inference_input_hash=frame.input_hash,
        membership_hash=frame.membership_hash,
        dsr_probability=getattr(model, "dsr_probability", 0.0),
        weights=risky_target_weights(weights),
    )


__all__ = [
    "RlPolicyOutcome",
    "build_inference_frame",
    "compute_rl_target_weights",
    "default_active_policy_path",
    "live_membership",
    "load_active_policy",
    "risky_target_weights",
    "unavailable",
]
