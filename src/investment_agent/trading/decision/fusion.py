"""숫자 예측과 네 개 desk 의견을 하나의 ExpectedReturnSignal로 합친다."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.trading.decision.contracts import AnalystSignal, ExpectedReturnSignal


DEFAULT_COMPONENT_WEIGHTS: dict[str, float] = {
    "numeric": 0.45,
    "market": 0.15,
    "fundamental": 0.15,
    "macro": 0.10,
    "event": 0.10,
    "debate": 0.05,
}


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ContractError(f"{field_name} must be finite")
    return parsed


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


@dataclass(frozen=True)
class NumericPrediction:
    """Naive/Ridge/GBM/PPO가 반환하는 거래 전 수익률 예측이다."""

    ticker: str
    as_of_at: str
    expected_1d_return: float
    expected_5d_return: float
    expected_20d_return: float
    probability_up: float
    confidence: float
    uncertainty: float
    model_id: str
    version: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ticker = str(self.ticker).upper().strip()
        if not ticker:
            raise ContractError("numeric prediction ticker is required")
        parse_datetime(self.as_of_at)
        for name in (
            "expected_1d_return", "expected_5d_return", "expected_20d_return",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        object.__setattr__(self, "probability_up", _clamp(_finite(self.probability_up, "probability_up"), 0.0, 1.0))
        object.__setattr__(self, "confidence", _clamp(_finite(self.confidence, "confidence"), 0.0, 1.0))
        object.__setattr__(self, "uncertainty", _clamp(_finite(self.uncertainty, "uncertainty"), 0.0, 1.0))
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "evidence_ids", tuple(sorted({str(item).strip() for item in self.evidence_ids if str(item).strip()})))
        if not str(self.model_id).strip() or not str(self.version).strip():
            raise ContractError("numeric prediction model_id and version are required")


@dataclass(frozen=True)
class FusionResult:
    """최종 signal과 컴포넌트별 기여를 함께 남기는 분석 결과."""

    signal: ExpectedReturnSignal
    contributions: tuple[tuple[str, float], ...]
    direction_dispersion: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal.to_dict(),
            "contributions": dict(self.contributions),
            "direction_dispersion": self.direction_dispersion,
        }


def _prediction(value: NumericPrediction | ExpectedReturnSignal | Mapping[str, Any]) -> NumericPrediction:
    if isinstance(value, NumericPrediction):
        return value
    if isinstance(value, ExpectedReturnSignal):
        return NumericPrediction(
            ticker=value.ticker,
            as_of_at=value.as_of_at,
            expected_1d_return=value.expected_1d_return,
            expected_5d_return=value.expected_5d_return,
            expected_20d_return=value.expected_20d_return,
            probability_up=value.probability_up,
            confidence=value.confidence,
            uncertainty=value.uncertainty,
            model_id=value.model_id,
            version=value.version,
            evidence_ids=value.evidence_ids,
        )
    if isinstance(value, Mapping):
        return NumericPrediction(
            ticker=str(value["ticker"]),
            as_of_at=str(value["as_of_at"]),
            expected_1d_return=float(value["expected_1d_return"]),
            expected_5d_return=float(value["expected_5d_return"]),
            expected_20d_return=float(value["expected_20d_return"]),
            probability_up=float(value["probability_up"]),
            confidence=float(value["confidence"]),
            uncertainty=float(value["uncertainty"]),
            model_id=str(value.get("model_id") or value.get("model") or "numeric"),
            version=str(value.get("version") or "v1"),
            evidence_ids=tuple(value.get("evidence_ids") or ()),
        )
    raise TypeError("unsupported numeric prediction")


def _desk_returns(signal: AnalystSignal) -> tuple[float, float, float]:
    five = signal.expected_return if signal.expected_return is not None else signal.direction * 0.02
    return five * 0.25, five, five * 2.5


def fuse_signals(
    *,
    ticker: str,
    as_of_at: str,
    desk_signals: Sequence[AnalystSignal] = (),
    numeric_predictions: Sequence[NumericPrediction | ExpectedReturnSignal | Mapping[str, Any]] = (),
    debate_signal: AnalystSignal | None = None,
    component_weights: Mapping[str, float] | None = None,
    version: str = "signal-fusion-v1",
) -> FusionResult:
    """모델 disagreement를 uncertainty로 보존하고 BUY/SELL 문장을 만들지 않는다."""
    normalized_ticker = str(ticker).upper().strip()
    as_of = parse_datetime(as_of_at).isoformat()
    predictions = tuple(_prediction(value) for value in numeric_predictions)
    all_desks = tuple(desk_signals) + ((debate_signal,) if debate_signal is not None else ())
    for signal in all_desks:
        if signal.ticker != normalized_ticker or signal.as_of_at != as_of:
            raise ContractError("fusion inputs must share ticker and as_of_at")
    for prediction in predictions:
        if prediction.ticker != normalized_ticker or parse_datetime(prediction.as_of_at).isoformat() != as_of:
            raise ContractError("numeric predictions must share ticker and as_of_at")
    if not all_desks and not predictions:
        raise ContractError("signal fusion requires at least one input")

    weights = dict(DEFAULT_COMPONENT_WEIGHTS)
    weights.update({str(key).lower(): float(value) for key, value in (component_weights or {}).items()})
    if any(value < 0.0 or not math.isfinite(value) for value in weights.values()):
        raise ValueError("fusion component weights must be finite and non-negative")
    components: list[tuple[str, tuple[float, float, float], float, float, tuple[str, ...], tuple[str, ...]]] = []
    if predictions:
        mean = tuple(
            sum(getattr(prediction, name) for prediction in predictions) / len(predictions)
            for name in ("expected_1d_return", "expected_5d_return", "expected_20d_return")
        )
        probability = sum(prediction.probability_up for prediction in predictions) / len(predictions)
        confidence = sum(prediction.confidence for prediction in predictions) / len(predictions)
        uncertainty = sum(prediction.uncertainty for prediction in predictions) / len(predictions)
        components.append(("numeric", mean, probability, confidence, tuple(
            evidence_id for prediction in predictions for evidence_id in prediction.evidence_ids
        ), ()))
    for signal in all_desks:
        returns = _desk_returns(signal)
        components.append((
            signal.domain,
            returns,
            0.5 + 0.5 * signal.direction,
            signal.confidence,
            signal.evidence_ids,
            signal.reasoning,
        ))
    total_weight = sum(weights.get(name, 0.0) * max(0.05, confidence) for name, _, _, confidence, _, _ in components)
    if total_weight <= 0.0:
        raise ContractError("fusion has no active component weight")
    expected = [0.0, 0.0, 0.0]
    probability = 0.0
    directions: list[float] = []
    uncertainty_terms: list[float] = []
    evidence_ids: set[str] = set()
    positives: list[str] = []
    negatives: list[str] = []
    contributions: list[tuple[str, float]] = []
    for name, returns, component_probability, confidence, ids, reasoning in components:
        effective = weights.get(name, 0.0) * max(0.05, confidence) / total_weight
        for index, value in enumerate(returns):
            expected[index] += effective * value
        probability += effective * component_probability
        direction = 2.0 * component_probability - 1.0
        directions.append(direction)
        uncertainty_terms.append((1.0 - confidence) * effective)
        evidence_ids.update(ids)
        contributions.append((name, round(effective, 12)))
        if direction >= 0.15:
            positives.append(f"{name}: {reasoning[0] if reasoning else 'positive direction'}")
        elif direction <= -0.15:
            negatives.append(f"{name}: {reasoning[0] if reasoning else 'negative direction'}")
    mean_direction = sum(directions) / len(directions) if directions else 0.0
    dispersion = max(directions) - min(directions) if directions else 0.0
    uncertainty = _clamp(sum(uncertainty_terms) + 0.5 * dispersion, 0.0, 1.0)
    return FusionResult(
        signal=ExpectedReturnSignal(
            ticker=normalized_ticker,
            as_of_at=as_of,
            expected_1d_return=expected[0],
            expected_5d_return=expected[1],
            expected_20d_return=expected[2],
            probability_up=_clamp(probability, 0.0, 1.0),
            confidence=_clamp(1.0 - uncertainty, 0.0, 1.0),
            uncertainty=uncertainty,
            preferred_horizon="5d",
            model_id="signal-fusion",
            version=version,
            major_positive_factors=tuple(positives[:5]),
            major_negative_factors=tuple(negatives[:5]),
            evidence_ids=tuple(sorted(evidence_ids)),
            metadata={
                "contributors": dict(contributions),
                "direction_mean": mean_direction,
                "numeric_model_count": len(predictions),
                "desk_count": len(all_desks),
            },
        ),
        contributions=tuple(contributions),
        direction_dispersion=dispersion,
    )


__all__ = [
    "DEFAULT_COMPONENT_WEIGHTS",
    "FusionResult",
    "NumericPrediction",
    "fuse_signals",
]
