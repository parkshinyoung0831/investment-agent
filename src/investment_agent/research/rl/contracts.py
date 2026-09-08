"""RL feature·미래 label·universe membership의 분리 저장 계약."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from investment_agent.trading.contracts import parse_datetime
from investment_agent.platform.serialization import canonical_json

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
_MEMBERSHIP_KINDS = {"live_tracked", "historical_point_in_time"}
_RESERVED_LABEL_FIELDS = {
    "forward_end_at",
    "forward_return",
    "benchmark_forward_return",
    "label",
    "label_available_at",
    "target",
}


class RLSafetyError(RuntimeError):
    """시간·membership·누수 오류 때문에 학습이나 추론을 중단해야 하는 경우다."""


class RLDataNotReadyError(RLSafetyError):
    """원장이 아직 안 찼을 뿐, 데이터가 틀린 것은 아닌 경우다.

    forward label은 미래 구간(기본 5거래일)이 닫혀야 확정된다. 그전까지 학습을
    멈추는 것은 맞지만, 그것을 실패로 보고하면 운영 로그가 무해한 오류로 덮여
    진짜 오류가 묻힌다. 학습을 막는다는 점은 같으므로 하위 타입으로 둔다."""


def _ticker(value: str) -> str:
    ticker = str(value).upper().strip()
    if ticker == "CASH" or not _TICKER_RE.fullmatch(ticker):
        raise ValueError(f"invalid RL ticker: {ticker}")
    return ticker


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _hash(prefix: str, payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


@dataclass(frozen=True)
class FeatureSnapshot:
    """as_of 시점에 실제로 이용 가능했던 값만 담고 미래 label은 금지한다."""

    feature_version: str
    as_of_at: str
    ticker: str
    available_at: str
    is_available: bool
    features: Mapping[str, float | None]
    source_ids: tuple[str, ...]
    provenance: Mapping[str, Any]
    input_hash: str = field(init=False)
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        version = str(self.feature_version).strip()
        if not version:
            raise ValueError("feature_version is required")
        as_of_at = parse_datetime(self.as_of_at).isoformat()
        available_at = parse_datetime(self.available_at).isoformat()
        if parse_datetime(available_at) > parse_datetime(as_of_at):
            raise RLSafetyError("feature available_at cannot be after as_of_at")
        if not isinstance(self.is_available, bool):
            raise ValueError("is_available must be boolean")
        if not isinstance(self.features, Mapping) or not self.features:
            raise ValueError("features must be a non-empty mapping")
        normalized_features: dict[str, float | None] = {}
        for raw_name, raw_value in self.features.items():
            name = str(raw_name).strip()
            if not name:
                raise ValueError("feature name must not be empty")
            if name.lower() in _RESERVED_LABEL_FIELDS:
                raise RLSafetyError(f"future label field is forbidden in feature snapshot: {name}")
            if name in normalized_features:
                raise ValueError(f"duplicate feature name: {name}")
            normalized_features[name] = None if raw_value is None else _finite(raw_value, name)
        raw_sources = tuple(self.source_ids)
        if any(not isinstance(value, str) for value in raw_sources):
            raise ValueError("source_ids must contain strings")
        normalized_sources = tuple(value.strip() for value in raw_sources if value.strip())
        if len(normalized_sources) != len(set(normalized_sources)):
            raise ValueError("source_ids must not contain duplicates")
        source_ids = tuple(sorted(normalized_sources))
        if not source_ids:
            raise RLSafetyError("feature snapshot requires source provenance")
        if not isinstance(self.provenance, Mapping) or not self.provenance:
            raise RLSafetyError("feature snapshot requires structured provenance")
        try:
            provenance = json.loads(canonical_json(dict(self.provenance)))
        except (TypeError, ValueError) as exc:
            raise ValueError("provenance must contain JSON-compatible values") from exc
        if not isinstance(provenance, dict) or any(
            not isinstance(key, str) or not key.strip() for key in provenance
        ):
            raise ValueError("provenance must be a non-empty object with string keys")
        ticker = _ticker(self.ticker)
        identity = {
            "feature_version": version,
            "as_of_at": as_of_at,
            "ticker": ticker,
            "available_at": available_at,
            "is_available": self.is_available,
            "features": normalized_features,
            "source_ids": source_ids,
            "provenance": provenance,
        }
        input_hash = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        object.__setattr__(self, "feature_version", version)
        object.__setattr__(self, "as_of_at", as_of_at)
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "features", MappingProxyType(normalized_features))
        object.__setattr__(self, "source_ids", source_ids)
        object.__setattr__(self, "provenance", MappingProxyType(provenance))
        object.__setattr__(self, "input_hash", input_hash)
        object.__setattr__(self, "snapshot_id", _hash("rl_feature", identity))

    def to_storage_row(self) -> dict[str, Any]:
        """label 컬럼이 물리적으로 들어갈 수 없는 feature 전용 payload."""
        return {
            "feature_version": self.feature_version,
            "as_of_at": self.as_of_at,
            "ticker": self.ticker,
            "available_at": self.available_at,
            "is_available": self.is_available,
            "features": dict(self.features),
            "source_ids": list(self.source_ids),
            "provenance": dict(self.provenance),
            "input_hash": self.input_hash,
        }


@dataclass(frozen=True)
class ForwardReturnLabel:
    """feature snapshot과 분리되어 미래 구간 종료 뒤에만 생성되는 label."""

    feature_version: str
    as_of_at: str
    ticker: str
    forward_end_at: str
    label_available_at: str
    forward_return: float
    benchmark_forward_return: float
    label_id: str = field(init=False)

    def __post_init__(self) -> None:
        version = str(self.feature_version).strip()
        if not version:
            raise ValueError("feature_version is required")
        as_of_at = parse_datetime(self.as_of_at).isoformat()
        forward_end_at = parse_datetime(self.forward_end_at).isoformat()
        label_available_at = parse_datetime(self.label_available_at).isoformat()
        if parse_datetime(forward_end_at) <= parse_datetime(as_of_at):
            raise RLSafetyError("forward_end_at must be after feature as_of_at")
        if parse_datetime(label_available_at) < parse_datetime(forward_end_at):
            raise RLSafetyError("label cannot be available before the forward window ends")
        forward_return = _finite(self.forward_return, "forward_return")
        benchmark_return = _finite(self.benchmark_forward_return, "benchmark_forward_return")
        if forward_return < -1.0 or benchmark_return < -1.0:
            raise ValueError("returns cannot be below -100%")
        ticker = _ticker(self.ticker)
        identity = {
            "feature_version": version,
            "as_of_at": as_of_at,
            "ticker": ticker,
            "forward_end_at": forward_end_at,
            "label_available_at": label_available_at,
            "forward_return": forward_return,
            "benchmark_forward_return": benchmark_return,
        }
        object.__setattr__(self, "feature_version", version)
        object.__setattr__(self, "as_of_at", as_of_at)
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "forward_end_at", forward_end_at)
        object.__setattr__(self, "label_available_at", label_available_at)
        object.__setattr__(self, "forward_return", forward_return)
        object.__setattr__(self, "benchmark_forward_return", benchmark_return)
        object.__setattr__(self, "label_id", _hash("rl_label", identity))

    def to_storage_row(self) -> dict[str, Any]:
        """feature 값이 물리적으로 들어갈 수 없는 label 전용 payload."""
        return {
            "feature_version": self.feature_version,
            "as_of_at": self.as_of_at,
            "ticker": self.ticker,
            "forward_end_at": self.forward_end_at,
            "label_available_at": self.label_available_at,
            "forward_return": self.forward_return,
            "benchmark_forward_return": self.benchmark_forward_return,
            "label_id": self.label_id,
        }


@dataclass(frozen=True)
class MembershipSnapshot:
    """live tracked 집합과 역사적 구성종목 snapshot을 명시적으로 구분한다."""

    effective_at: str
    symbols: tuple[str, ...]
    source_id: str
    source_kind: str

    def __post_init__(self) -> None:
        effective_at = parse_datetime(self.effective_at).isoformat()
        symbols = tuple(sorted({_ticker(value) for value in self.symbols}))
        if not symbols:
            raise ValueError("membership snapshot must contain symbols")
        source_id = str(self.source_id).strip()
        if not source_id:
            raise RLSafetyError("membership snapshot requires source provenance")
        if self.source_kind not in _MEMBERSHIP_KINDS:
            raise ValueError(f"invalid membership source_kind: {self.source_kind}")
        object.__setattr__(self, "effective_at", effective_at)
        object.__setattr__(self, "symbols", symbols)
        object.__setattr__(self, "source_id", source_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_at": self.effective_at,
            "symbols": list(self.symbols),
            "source_id": self.source_id,
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True)
class MembershipTimeline:
    """목적과 다른 universe를 요청하면 fail-closed하는 point-in-time timeline."""

    source_kind: str
    snapshots: tuple[MembershipSnapshot, ...]

    def __post_init__(self) -> None:
        if self.source_kind not in _MEMBERSHIP_KINDS:
            raise ValueError(f"invalid membership source_kind: {self.source_kind}")
        snapshots = tuple(self.snapshots)
        if not snapshots or any(not isinstance(item, MembershipSnapshot) for item in snapshots):
            raise ValueError("membership timeline requires MembershipSnapshot values")
        snapshots = tuple(sorted(snapshots, key=lambda item: (item.effective_at, item.source_id)))
        if any(item.source_kind != self.source_kind for item in snapshots):
            raise RLSafetyError("membership timeline cannot mix live and historical snapshots")
        effective = [item.effective_at for item in snapshots]
        if len(effective) != len(set(effective)):
            raise ValueError("only one membership snapshot is allowed per effective_at")
        if self.source_kind == "live_tracked" and len(snapshots) != 1:
            raise RLSafetyError("live tracked membership requires exactly one current snapshot")
        object.__setattr__(self, "snapshots", snapshots)

    def members_at(
        self,
        as_of_at: str | datetime,
        *,
        purpose: str,
        max_live_age_seconds: float | None = None,
    ) -> frozenset[str]:
        point = parse_datetime(as_of_at)
        required_mode = {
            "historical_training": "historical_point_in_time",
            "live_inference": "live_tracked",
        }.get(purpose)
        if required_mode is None:
            raise ValueError("purpose must be historical_training or live_inference")
        if self.source_kind != required_mode:
            raise RLSafetyError(
                f"{purpose} requires {required_mode} membership, got {self.source_kind}"
            )
        eligible = [item for item in self.snapshots if parse_datetime(item.effective_at) <= point]
        if not eligible:
            raise RLSafetyError(f"missing {required_mode} membership for {point.isoformat()}")
        selected = eligible[-1]
        if purpose == "live_inference" and max_live_age_seconds is not None:
            if max_live_age_seconds <= 0:
                raise ValueError("max_live_age_seconds must be positive")
            age = (point - parse_datetime(selected.effective_at)).total_seconds()
            if age > max_live_age_seconds:
                raise RLSafetyError(
                    f"live tracked membership is stale: {age:.3f}s > {max_live_age_seconds:.3f}s"
                )
        return frozenset(selected.symbols)

    @property
    def hash(self) -> str:
        payload = {"source_kind": self.source_kind, "snapshots": [item.to_dict() for item in self.snapshots]}
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def normalize_symbols(values: Iterable[str]) -> tuple[str, ...]:
    """학습·추론 action 축에 쓸 정렬된 종목 집합."""
    symbols = tuple(sorted({_ticker(value) for value in values}))
    if not symbols:
        raise ValueError("RL symbols must not be empty")
    return symbols


@dataclass(frozen=True)
class RewardConfig:
    return_weight: float = 1.0
    alpha_weight: float = 0.5
    drawdown_penalty: float = 0.5
    volatility_penalty: float = 0.1
    turnover_penalty: float = 0.05
    transaction_cost_rate: float = 0.001
    concentration_penalty: float = 0.1
    volatility_window: int = 20

    def __post_init__(self) -> None:
        if self.volatility_window < 2:
            raise ValueError("volatility_window must be at least 2")
        for name in self.__dataclass_fields__:
            if name == "volatility_window":
                continue
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("reward weights and costs must be numeric")
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError("reward weights and costs must be finite and non-negative")


__all__ = [
    "FeatureSnapshot",
    "ForwardReturnLabel",
    "MembershipSnapshot",
    "MembershipTimeline",
    "RLSafetyError",
    "RewardConfig",
    "normalize_symbols",
]
