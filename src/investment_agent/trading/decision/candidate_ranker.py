"""현재 tracked universe 전체를 공정하게 순환시키는 시점 안전 후보 랭커."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Mapping, Sequence

from investment_agent.trading.evidence.tools import fundamental_statistics

from investment_agent.platform.serialization import (
    finite_float as _finite,
    normalize_ticker as _ticker,
    parse_datetime,
)

_DOMAIN_WEIGHTS = {
    "market": 0.30,
    "technical": 0.20,
    "fundamentals": 0.25,
    "segments": 0.10,
    "gurus": 0.15,
}
LIVE_CANDIDATE_MAX_AGE_HOURS = 24
_FUTURE_CLOCK_SKEW = timedelta(minutes=5)


def _parse_optional_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    return parse_datetime(value).astimezone(timezone.utc)


def validate_live_candidate_as_of(
    as_of_at: datetime | str,
    *,
    now_at: datetime | str | None = None,
    max_age_hours: int = LIVE_CANDIDATE_MAX_AGE_HOURS,
) -> datetime:
    """현재 universe·비버전 자식 데이터로 과거 후보를 재구성하지 못하게 한다."""
    if max_age_hours < 1 or max_age_hours > 72:
        raise ValueError("candidate max age must be between 1 and 72 hours")
    as_of = parse_datetime(as_of_at).astimezone(timezone.utc)
    now = (
        parse_datetime(now_at).astimezone(timezone.utc)
        if now_at is not None else datetime.now(timezone.utc)
    )
    if as_of > now + _FUTURE_CLOCK_SKEW:
        raise ValueError("candidate as_of_at is in the future")
    if now - as_of > timedelta(hours=max_age_hours):
        raise ValueError(
            "candidate ranking is live-only; historical as_of requires versioned "
            "segment_metrics and gurus positions"
        )
    return as_of


@dataclass(frozen=True)
class CandidateFeatures:
    """후보 정렬에만 쓰는 작은 구조화 snapshot.

    값의 방향을 곧바로 매수 신호로 쓰지 않는다. 이 랭커는 큰 변화나 극단값을 먼저
    Bull/Bear 토론에 올릴 뿐이며 최종 매수·매도 판단은 TradingAgents와 Risk Gate가 한다.
    """

    ticker: str
    last_analyzed_at: datetime | str | None = None
    return_20d: float | None = None
    volume_ratio_20d: float | None = None
    rsi14: float | None = None
    macd_spread_pct: float | None = None
    revenue_growth_yoy: float | None = None
    operating_margin: float | None = None
    segment_concentration: float | None = None
    segment_quality: float | None = None
    guru_holder_count: float | None = None
    guru_new_buy_count: float | None = None
    guru_add_count: float | None = None
    guru_hold_count: float | None = None
    guru_reduce_count: float | None = None
    guru_exit_count: float | None = None
    guru_total_value_usd: float | None = None
    guru_avg_quantity_change_pct: float | None = None
    guru_max_weight_pct: float | None = None
    guru_consensus: str | None = None

    def __post_init__(self) -> None:
        symbol = _ticker(self.ticker)
        if not symbol:
            raise ValueError("candidate ticker is required")
        object.__setattr__(self, "ticker", symbol)
        object.__setattr__(
            self,
            "last_analyzed_at",
            _parse_optional_datetime(self.last_analyzed_at),
        )
        for field_name in (
            "return_20d",
            "volume_ratio_20d",
            "rsi14",
            "macd_spread_pct",
            "revenue_growth_yoy",
            "operating_margin",
            "segment_concentration",
            "segment_quality",
            "guru_holder_count",
            "guru_new_buy_count",
            "guru_add_count",
            "guru_hold_count",
            "guru_reduce_count",
            "guru_exit_count",
            "guru_total_value_usd",
            "guru_avg_quantity_change_pct",
            "guru_max_weight_pct",
        ):
            value = getattr(self, field_name)
            if value is not None and _finite(value) is None:
                raise ValueError(f"candidate feature must be finite: {field_name}")


@dataclass(frozen=True)
class CandidateRank:
    """재현 가능한 후보 점수와 도메인별 기여도."""

    ticker: str
    score: float
    domain_scores: tuple[tuple[str, float], ...]
    domain_count: int
    last_analyzed_at: datetime | None


def _group_by_ticker(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        symbol = _ticker(row.get("ticker"))
        if symbol:
            grouped.setdefault(symbol, []).append(row)
    return grouped


def _market_features(rows: Sequence[Mapping[str, Any]]) -> tuple[float | None, float | None, float | None]:
    ordered = sorted(rows, key=lambda row: str(row.get("trade_date") or ""))
    valid = [
        row for row in ordered
        if (_finite(row.get("close")) or 0) > 0
    ]
    if not valid:
        return None, None, None
    closes = [float(row["close"]) for row in valid]
    return_20d = closes[-1] / closes[-21] - 1 if len(closes) >= 21 else None
    previous_volumes = [
        value for value in (_finite(row.get("volume")) for row in valid[-21:-1])
        if value is not None and value > 0
    ]
    latest_volume = _finite(valid[-1].get("volume"))
    baseline = median(previous_volumes) if previous_volumes else None
    volume_ratio = (
        latest_volume / baseline
        if latest_volume is not None and baseline not in (None, 0)
        else None
    )
    return return_20d, volume_ratio, closes[-1]


def _latest(rows: Sequence[Mapping[str, Any]], *columns: str) -> Mapping[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda row: tuple(str(row.get(column) or "") for column in columns))


def assemble_candidate_features(
    tickers: Sequence[str],
    *,
    last_analyzed_at: Mapping[str, datetime | str | None],
    market_rows: Sequence[Mapping[str, Any]],
    technical_rows: Sequence[Mapping[str, Any]],
    fundamental_rows: Sequence[Mapping[str, Any]],
    segment_signals: Mapping[str, Mapping[str, Any]],
    guru_signals: Mapping[str, Mapping[str, Any]],
) -> tuple[CandidateFeatures, ...]:
    """DB에서 시점 필터된 행을 종목별 작은 후보 snapshot으로 축약한다."""
    market_by_ticker = _group_by_ticker(market_rows)
    technical_by_ticker = _group_by_ticker(technical_rows)
    fundamental_by_ticker = _group_by_ticker(fundamental_rows)
    result: list[CandidateFeatures] = []
    for symbol in sorted({_ticker(value) for value in tickers if _ticker(value)}):
        return_20d, volume_ratio, latest_close = _market_features(
            market_by_ticker.get(symbol, ())
        )
        technical = _latest(
            technical_by_ticker.get(symbol, ()), "trade_date", "ingested_at"
        )
        macd = _finite(technical.get("macd")) if technical else None
        macd_signal = _finite(technical.get("macd_signal")) if technical else None
        macd_spread = (
            (macd - macd_signal) / latest_close
            if macd is not None and macd_signal is not None and latest_close not in (None, 0)
            else None
        )
        fundamentals_desc = sorted(
            fundamental_by_ticker.get(symbol, ()),
            key=lambda row: (
                str(row.get("filed_at") or ""),
                str(row.get("period_end") or ""),
            ),
            reverse=True,
        )
        fundamental = fundamental_statistics(fundamentals_desc)
        segment = segment_signals.get(symbol, {})
        guru = guru_signals.get(symbol, {})
        result.append(CandidateFeatures(
            ticker=symbol,
            last_analyzed_at=last_analyzed_at.get(symbol),
            return_20d=return_20d,
            volume_ratio_20d=volume_ratio,
            rsi14=_finite(technical.get("rsi14")) if technical else None,
            macd_spread_pct=macd_spread,
            revenue_growth_yoy=_finite(fundamental.get("revenue_growth_yoy")),
            operating_margin=_finite(fundamental.get("operating_margin")),
            segment_concentration=_finite(segment.get("concentration")),
            segment_quality=_finite(segment.get("quality")),
            guru_holder_count=_finite(guru.get("holder_count")),
            guru_new_buy_count=_finite(guru.get("new_buy_count")),
            guru_add_count=_finite(guru.get("add_count")),
            guru_hold_count=_finite(guru.get("hold_count")),
            guru_reduce_count=_finite(guru.get("reduce_count")),
            guru_exit_count=_finite(guru.get("exit_count")),
            guru_total_value_usd=_finite(guru.get("total_value_usd")),
            guru_avg_quantity_change_pct=_finite(guru.get("avg_quantity_change_pct")),
            guru_max_weight_pct=_finite(guru.get("max_weight_pct")),
            guru_consensus=(str(guru["consensus"]) if guru.get("consensus") else None),
        ))
    return tuple(result)


def _dense_percentiles(
    features: Sequence[CandidateFeatures],
    extractor: Any,
) -> dict[str, float]:
    values: dict[str, float] = {}
    for feature in features:
        value = extractor(feature)
        parsed = _finite(value)
        if parsed is not None:
            values[feature.ticker] = parsed
    unique = sorted(set(values.values()))
    if not unique:
        return {}
    if len(unique) == 1:
        return {ticker: 0.5 for ticker in values}
    by_value = {value: index / (len(unique) - 1) for index, value in enumerate(unique)}
    return {ticker: by_value[value] for ticker, value in values.items()}


def _mean_available(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def rank_candidate_features(
    features: Sequence[CandidateFeatures],
    *,
    as_of_at: datetime | str,
    limit: int,
) -> tuple[CandidateRank, ...]:
    """미분석/가장 오래된 종목을 먼저 두고 같은 cohort를 신호 크기로 정렬한다."""
    if limit < 1:
        raise ValueError("candidate limit must be positive")
    as_of = parse_datetime(as_of_at).astimezone(timezone.utc)
    by_ticker = {feature.ticker: feature for feature in features}
    if len(by_ticker) != len(features):
        raise ValueError("candidate features contain duplicate tickers")
    for feature in features:
        if feature.last_analyzed_at is not None and feature.last_analyzed_at > as_of:
            raise ValueError("candidate coverage history exceeds as_of_at")

    market_return = _dense_percentiles(
        features,
        lambda row: abs(row.return_20d) if row.return_20d is not None else None,
    )
    market_volume = _dense_percentiles(
        features,
        lambda row: abs(math.log(row.volume_ratio_20d))
        if row.volume_ratio_20d is not None and row.volume_ratio_20d > 0 else None,
    )
    technical_rsi = _dense_percentiles(
        features,
        lambda row: abs(row.rsi14 - 50.0) if row.rsi14 is not None else None,
    )
    technical_macd = _dense_percentiles(
        features,
        lambda row: abs(row.macd_spread_pct)
        if row.macd_spread_pct is not None else None,
    )
    fundamental_growth = _dense_percentiles(
        features,
        lambda row: abs(row.revenue_growth_yoy)
        if row.revenue_growth_yoy is not None else None,
    )
    fundamental_margin = _dense_percentiles(
        features,
        lambda row: abs(row.operating_margin)
        if row.operating_margin is not None else None,
    )
    segment_concentration = _dense_percentiles(features, lambda row: row.segment_concentration)
    segment_quality = _dense_percentiles(features, lambda row: row.segment_quality)
    guru_count = _dense_percentiles(features, lambda row: row.guru_holder_count)
    guru_value = _dense_percentiles(
        features,
        lambda row: math.log1p(row.guru_total_value_usd)
        if row.guru_total_value_usd is not None and row.guru_total_value_usd >= 0 else None,
    )

    ranked: list[CandidateRank] = []
    for feature in features:
        symbol = feature.ticker
        domains = {
            "market": _mean_available(market_return.get(symbol), market_volume.get(symbol)),
            "technical": _mean_available(technical_rsi.get(symbol), technical_macd.get(symbol)),
            "fundamentals": _mean_available(
                fundamental_growth.get(symbol), fundamental_margin.get(symbol)
            ),
            "segments": _mean_available(
                segment_concentration.get(symbol), segment_quality.get(symbol)
            ),
            "gurus": _mean_available(guru_count.get(symbol), guru_value.get(symbol)),
        }
        available = {name: value for name, value in domains.items() if value is not None}
        if available:
            weight_sum = sum(_DOMAIN_WEIGHTS[name] for name in available)
            raw_score = sum(
                _DOMAIN_WEIGHTS[name] * value for name, value in available.items()
            ) / weight_sum
            coverage_multiplier = 0.80 + 0.20 * len(available) / len(_DOMAIN_WEIGHTS)
            score = raw_score * coverage_multiplier
        else:
            score = 0.0
        ranked.append(CandidateRank(
            ticker=symbol,
            score=round(score, 12),
            domain_scores=tuple(
                (name, round(value, 12)) for name, value in sorted(available.items())
            ),
            domain_count=len(available),
            last_analyzed_at=feature.last_analyzed_at,
        ))

    never = datetime.min.replace(tzinfo=timezone.utc)
    ranked.sort(key=lambda row: (
        row.last_analyzed_at or never,
        -row.score,
        row.ticker,
    ))
    return tuple(ranked[:limit])


__all__ = [
    "CandidateFeatures",
    "CandidateRank",
    "LIVE_CANDIDATE_MAX_AGE_HOURS",
    "assemble_candidate_features",
    "fundamental_statistics",
    "rank_candidate_features",
    "validate_live_candidate_as_of",
]
