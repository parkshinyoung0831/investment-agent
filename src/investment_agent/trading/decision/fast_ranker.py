"""503개 전체를 값싼 숫자 연산으로 줄이는 Fast Ranker."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from investment_agent.platform.serialization import (
    canonical_json,
    finite_float as _finite,
    normalize_ticker as _ticker,
    parse_datetime,
)
from investment_agent.trading.decision.candidate_ranker import (
    CandidateFeatures,
    CandidateRank,
    rank_candidate_features,
)


_FIELDS = (
    "price_anomaly", "volume_anomaly", "momentum", "technical_regime_change",
    "fundamental_change", "estimate_revision", "sec_event", "news_velocity",
    "social_velocity", "event_importance", "portfolio_relevance",
)
_DEFAULT_WEIGHTS = {
    "price_anomaly": 0.10,
    "volume_anomaly": 0.08,
    "momentum": 0.10,
    "technical_regime_change": 0.10,
    "fundamental_change": 0.12,
    "estimate_revision": 0.10,
    "sec_event": 0.10,
    "news_velocity": 0.08,
    "social_velocity": 0.04,
    "event_importance": 0.10,
    "portfolio_relevance": 0.08,
}


@dataclass(frozen=True)
class FastRankerPolicy:
    """매수 확률이 아니라 깊이 분석 우선순위를 조정하는 policy."""

    version: str = "fast-ranker-v1"
    baseline_weight: float = 0.60
    numeric_weight: float = 0.40
    max_candidates: int = 30
    domain_weights: tuple[tuple[str, float], ...] = tuple(_DEFAULT_WEIGHTS.items())

    def __post_init__(self) -> None:
        if not str(self.version).strip():
            raise ValueError("ranker version is required")
        if not 0.0 <= self.baseline_weight <= 1.0 or not 0.0 <= self.numeric_weight <= 1.0:
            raise ValueError("ranker weights must be between 0 and 1")
        if self.baseline_weight + self.numeric_weight <= 0.0:
            raise ValueError("at least one ranker component must be enabled")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        weights = dict(self.domain_weights)
        if set(weights) != set(_FIELDS) or any(value < 0.0 or not math.isfinite(float(value)) for value in weights.values()):
            raise ValueError("domain_weights must cover every fast-ranker field")
        if sum(weights.values()) <= 0.0:
            raise ValueError("domain_weights must have a positive sum")

    @property
    def hash(self) -> str:
        import hashlib
        return hashlib.sha256(canonical_json(asdict(self)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FastRankFeatures:
    """기존 CandidateFeatures에 event·portfolio relevance를 더한 작은 숫자 입력."""

    ticker: str
    last_analyzed_at: datetime | str | None = None
    price_anomaly: float | None = None
    volume_anomaly: float | None = None
    momentum: float | None = None
    technical_regime_change: float | None = None
    fundamental_change: float | None = None
    estimate_revision: float | None = None
    sec_event: float | None = None
    news_velocity: float | None = None
    social_velocity: float | None = None
    event_importance: float | None = None
    portfolio_relevance: float | None = None
    baseline: CandidateFeatures | None = None

    def __post_init__(self) -> None:
        ticker = _ticker(self.ticker)
        if not ticker:
            raise ValueError("fast ranker ticker is required")
        last = None if self.last_analyzed_at is None else parse_datetime(self.last_analyzed_at).astimezone(timezone.utc)
        for field_name in _FIELDS:
            value = getattr(self, field_name)
            if value is not None and _finite(value) is None:
                raise ValueError(f"fast ranker feature must be finite: {field_name}")
        if self.baseline is not None and self.baseline.ticker != ticker:
            raise ValueError("baseline candidate feature ticker does not match fast ranker ticker")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "last_analyzed_at", last)

    @classmethod
    def from_candidate_features(
        cls,
        feature: CandidateFeatures,
        *,
        event_features: Mapping[str, Any] | None = None,
        portfolio_relevance: float | None = None,
    ) -> "FastRankFeatures":
        """기존 후보 snapshot을 폐기하지 않고 새 screen 입력으로 확장한다."""
        event = dict(event_features or {})
        return cls(
            ticker=feature.ticker,
            last_analyzed_at=feature.last_analyzed_at,
            price_anomaly=abs(feature.return_20d) if feature.return_20d is not None else None,
            volume_anomaly=(abs(math.log(feature.volume_ratio_20d))
                            if feature.volume_ratio_20d is not None and feature.volume_ratio_20d > 0 else None),
            momentum=feature.return_20d,
            technical_regime_change=feature.macd_spread_pct,
            fundamental_change=feature.revenue_growth_yoy,
            estimate_revision=event.get("estimate_revision"),
            sec_event=event.get("sec_event"),
            news_velocity=event.get("news_velocity"),
            social_velocity=event.get("social_velocity"),
            event_importance=event.get("event_importance"),
            portfolio_relevance=portfolio_relevance,
            baseline=feature,
        )


@dataclass(frozen=True)
class FastCandidateRank:
    """최종 투자 신호가 아닌 deep-analysis 우선순위 결과."""

    ticker: str
    score: float
    rank: int
    domain_scores: tuple[tuple[str, float], ...]
    domain_count: int
    last_analyzed_at: datetime | None
    score_purpose: str = "deep_analysis_priority"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "score": self.score,
            "rank": self.rank,
            "domain_scores": dict(self.domain_scores),
            "domain_count": self.domain_count,
            "last_analyzed_at": self.last_analyzed_at.isoformat() if self.last_analyzed_at else None,
            "score_purpose": self.score_purpose,
        }


def _percentiles(features: Sequence[FastRankFeatures], field_name: str) -> dict[str, float]:
    values = {
        feature.ticker: abs(parsed)
        for feature in features
        if (parsed := _finite(getattr(feature, field_name))) is not None
    }
    unique = sorted(set(values.values()))
    if not unique:
        return {}
    if len(unique) == 1:
        return {ticker: 0.5 for ticker in values}
    positions = {value: index / (len(unique) - 1) for index, value in enumerate(unique)}
    return {ticker: positions[value] for ticker, value in values.items()}


def rank_fast_candidates(
    features: Sequence[FastRankFeatures],
    *,
    as_of_at: str | datetime,
    limit: int,
    policy: FastRankerPolicy | None = None,
    baseline_features: Sequence[CandidateFeatures] | None = None,
) -> tuple[FastCandidateRank, ...]:
    """cheap screening 결과를 오래된 coverage 우선으로 정렬한다."""
    if limit < 1:
        raise ValueError("candidate limit must be positive")
    policy = policy or FastRankerPolicy()
    as_of = parse_datetime(as_of_at).astimezone(timezone.utc)
    by_ticker = {feature.ticker: feature for feature in features}
    if len(by_ticker) != len(features):
        raise ValueError("fast ranker features contain duplicate tickers")
    for feature in features:
        if feature.last_analyzed_at is not None and feature.last_analyzed_at > as_of:
            raise ValueError("candidate coverage history exceeds as_of_at")

    baseline_rows = tuple(baseline_features or tuple(
        feature.baseline for feature in features if feature.baseline is not None
    ))
    baseline_by_ticker: dict[str, CandidateRank] = {}
    if baseline_rows:
        baseline_by_ticker = {
            row.ticker: row for row in rank_candidate_features(
                baseline_rows,
                as_of_at=as_of,
                limit=len(baseline_rows),
            )
        }
    percentiles = {field_name: _percentiles(features, field_name) for field_name in _FIELDS}
    weights = dict(policy.domain_weights)
    ranked: list[FastCandidateRank] = []
    for feature in features:
        available = {
            field_name: percentiles[field_name][feature.ticker]
            for field_name in _FIELDS
            if feature.ticker in percentiles[field_name]
        }
        weight_sum = sum(weights[name] for name in available)
        numeric_score = (
            sum(weights[name] * value for name, value in available.items()) / weight_sum
            if weight_sum else 0.0
        )
        baseline = baseline_by_ticker.get(feature.ticker)
        if baseline is None:
            score = numeric_score
        elif numeric_score == 0.0 and not available:
            score = baseline.score
        else:
            total_weight = policy.baseline_weight + policy.numeric_weight
            score = (
                policy.baseline_weight * baseline.score + policy.numeric_weight * numeric_score
            ) / total_weight
        coverage = 0.80 + 0.20 * len(available) / len(_FIELDS)
        score *= coverage
        ranked.append(FastCandidateRank(
            ticker=feature.ticker,
            score=round(score, 12),
            rank=0,
            domain_scores=tuple((name, round(value, 12)) for name, value in sorted(available.items())),
            domain_count=len(available),
            last_analyzed_at=feature.last_analyzed_at,
        ))
    never = datetime.min.replace(tzinfo=timezone.utc)
    ranked.sort(key=lambda row: (row.last_analyzed_at or never, -row.score, row.ticker))
    result = []
    for index, row in enumerate(ranked[:min(limit, policy.max_candidates)], start=1):
        result.append(FastCandidateRank(
            ticker=row.ticker,
            score=row.score,
            rank=index,
            domain_scores=row.domain_scores,
            domain_count=row.domain_count,
            last_analyzed_at=row.last_analyzed_at,
        ))
    return tuple(result)


__all__ = [
    "FastCandidateRank",
    "FastRankFeatures",
    "FastRankerPolicy",
    "rank_fast_candidates",
]
