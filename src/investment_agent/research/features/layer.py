"""학습과 live inference가 함께 쓰는 point-in-time feature 정의."""
from __future__ import annotations

import hashlib
import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from investment_agent.trading.contracts import EvidenceBundle, parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.research.rl.contracts import FeatureSnapshot, ForwardReturnLabel, RLSafetyError

# feature 계약 세대. `rl_feature_snapshots`의 identity 구성요소이며, 컬럼 계약이
# 바뀌면 snapshot과 label이 다른 세대로 분리된다.
FEATURE_VERSION = "v3"
HORIZONS = (1, 5, 20)

# 20거래일 수익률은 오늘 종가와 20거래일 전 종가가 둘 다 필요하다. ContextBuilder가
# 이보다 적게 넘기면 그 feature는 예외 없이 영구 결측이 되므로 상수를 공유한다.
REQUIRED_BARS = max(HORIZONS) + 1

# 거시는 series_id로 컬럼을 동적 생성하지 않는다. 그날 수집이 하나 빠지면 행마다
# 컬럼 수가 달라져 dataset 결합 자체가 실패하기 때문이다. S&P 500 종목의 regime
# 판단에 쓰는 지표만 남기고 한국 시장 series는 제외한다.
MACRO_SERIES = (
    "BEI_10Y", "BREADTH_200DMA", "CAPE", "COPPER", "DXY", "FEAR_GREED",
    "GOLD", "HY_SPREAD", "MOVE", "PCC", "SPREAD_10Y2Y", "SPREAD_10Y3M",
    "TNX", "US02Y", "VIX", "WTI",
)
_MACRO_SET = frozenset(MACRO_SERIES)

# 결측 지표 접미사. 값을 대체하더라도 관측이었는지 대체였는지는 남긴다.
MISSING_SUFFIX = "__is_missing"

# EvidenceBundle이 비어 있어도 항상 셀 수 있으므로 결측 지표를 붙이지 않는다.
# 상수 컬럼은 분산이 0이라 모델 입력에서 잡음만 만든다.
ALWAYS_KNOWN_FEATURES = ("evidence_domain_count", "missing_domain_count")

_MARKET_FEATURES = (
    *(f"price_return_{horizon}d" for horizon in HORIZONS),
    "price_volatility_20d",
)
_TECHNICAL_FEATURES = ("technical_rsi14", "technical_macd", "technical_macd_signal")
_FUNDAMENTAL_FEATURES = (
    "fundamental_revenue_growth",
    "fundamental_net_income_growth",
    "fundamental_operating_margin",
    "fundamental_debt_to_assets",
)
_GURU_FIELDS = (
    "holder_count", "new_buy_count", "add_count", "hold_count", "reduce_count",
    "exit_count", "total_value_usd", "avg_quantity_change_pct", "max_weight_pct",
)
_GURU_FEATURES = tuple(f"guru_{name}" for name in _GURU_FIELDS)

# 밸류에이션은 EvidenceBundle이 아니라 trading의 valuation 관측값에서 온다.
# 적자·자본잠식 구간은 원장에서 이미 None이라 여기서 0으로 바꾸지 않는다.
_VALUATION_RATIOS = ("pe_ttm", "pb", "ps_ttm", "fcf_yield")
_VALUATION_FEATURES = (
    *(f"valuation_{name}" for name in _VALUATION_RATIOS),
    "valuation_market_cap_log",
)
_MACRO_FEATURES = tuple(f"macro_{series.lower()}" for series in MACRO_SERIES)

# 결측 가능한 feature. 도메인이 통째로 비어도 컬럼은 남고 값만 None이 된다.
OPTIONAL_FEATURES = (
    *_MARKET_FEATURES, *_TECHNICAL_FEATURES, *_FUNDAMENTAL_FEATURES,
    *_GURU_FEATURES, *_MACRO_FEATURES, *_VALUATION_FEATURES,
)

# snapshot에 실제로 들어가는 전체 컬럼. 이 집합은 모든 종목·모든 날짜에서 같다.
FEATURE_COLUMNS = (
    *ALWAYS_KNOWN_FEATURES,
    *OPTIONAL_FEATURES,
    *(f"{name}{MISSING_SUFFIX}" for name in OPTIONAL_FEATURES),
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _close_returns(rows: Iterable[Mapping[str, Any]]) -> dict[str, float | None]:
    ordered = sorted(rows, key=lambda row: str(row.get("trade_date") or ""), reverse=True)
    closes = [_number(row.get("close")) for row in ordered]
    result: dict[str, float | None] = {}
    for horizon in HORIZONS:
        value = None
        if len(closes) > horizon and closes[0] is not None and closes[horizon] not in (None, 0.0):
            value = float(closes[0]) / float(closes[horizon]) - 1.0
        result[f"price_return_{horizon}d"] = value
    daily = []
    for current, previous in zip(closes, closes[1:]):
        if current is not None and previous not in (None, 0.0):
            daily.append(float(current) / float(previous) - 1.0)
        if len(daily) >= 20:
            break
    if len(daily) >= 2:
        mean = math.fsum(daily) / len(daily)
        result["price_volatility_20d"] = math.sqrt(
            math.fsum((value - mean) ** 2 for value in daily) / (len(daily) - 1)
        )
    else:
        result["price_volatility_20d"] = None
    return result


def _technical(payload: Mapping[str, Any]) -> dict[str, float | None]:
    return {
        "technical_rsi14": _number(payload.get("rsi14")),
        "technical_macd": _number(payload.get("macd")),
        "technical_macd_signal": _number(payload.get("macd_signal")),
    }


def _fundamental(payload: Mapping[str, Any]) -> dict[str, float | None]:
    filings = payload.get("filings")
    rows = filings if isinstance(filings, list) else []
    latest = rows[0] if rows and isinstance(rows[0], Mapping) else {}
    previous = rows[1] if len(rows) > 1 and isinstance(rows[1], Mapping) else {}

    def growth(field: str) -> float | None:
        current = _number(latest.get(field))
        prior = _number(previous.get(field))
        if current is None or prior in (None, 0.0):
            return None
        return current / abs(prior) - 1.0

    revenue = _number(latest.get("revenue"))
    operating = _number(latest.get("operating_income_loss"))
    assets = _number(latest.get("assets"))
    debt = _number(latest.get("total_debt_including_current"))
    return {
        "fundamental_revenue_growth": growth("revenue"),
        "fundamental_net_income_growth": growth("net_income"),
        "fundamental_operating_margin": (
            operating / revenue if operating is not None and revenue not in (None, 0.0) else None
        ),
        "fundamental_debt_to_assets": (
            debt / assets if debt is not None and assets not in (None, 0.0) else None
        ),
    }


def _macro(payload: Mapping[str, Any]) -> dict[str, float | None]:
    """allowlist에 있는 series만 고정 컬럼으로 반환한다."""
    rows = payload.get("latest_observations")
    result: dict[str, float | None] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        series_id = str(row.get("series_id") or "").strip().upper()
        if series_id in _MACRO_SET:
            result[f"macro_{series_id.lower()}"] = _number(row.get("value"))
    return result


def _gurus(payload: Mapping[str, Any]) -> dict[str, float | None]:
    """공개 시각을 통과한 13F raw feature만 RL 입력에 넣는다."""
    values = payload.get("features") if isinstance(payload, Mapping) else None
    source = values if isinstance(values, Mapping) else {}
    return {f"guru_{name}": _number(source.get(name)) for name in _GURU_FIELDS}


def _valuation(
    observation: Mapping[str, Any] | None,
    *,
    as_of: datetime,
) -> dict[str, float | None]:
    """PIT 밸류에이션 원장의 관측값만 feature로 받는다.

    가용시각이 판단 시점보다 늦으면 통째로 버린다 — 이 표는 EvidenceBundle 계약을
    거치지 않으므로 여기서 한 번 더 검사해야 한다. 시가총액은 규모가 수십억~수조로
    벌어져 그대로 쓰면 회귀가 큰 종목에만 끌려가므로 log를 취한다.
    """
    empty: dict[str, float | None] = {name: None for name in _VALUATION_FEATURES}
    if not isinstance(observation, Mapping) or not observation:
        return empty
    available_at = observation.get("available_at")
    if not available_at or parse_datetime(str(available_at)) > as_of:
        return empty
    result = dict(empty)
    for name in _VALUATION_RATIOS:
        result[f"valuation_{name}"] = _number(observation.get(name))
    market_cap = _number(observation.get("market_cap"))
    if market_cap is not None and market_cap > 0:
        result["valuation_market_cap_log"] = math.log(market_cap)
    return result


@dataclass(frozen=True)
class FeatureBundle:
    """feature 값과 정의 hash를 함께 전달해 training-serving skew를 탐지한다."""

    snapshot: FeatureSnapshot
    definition_version: str
    definition_hash: str
    horizons: tuple[int, ...] = HORIZONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot.to_storage_row(),
            "snapshot_id": self.snapshot.snapshot_id,
            "definition_version": self.definition_version,
            "definition_hash": self.definition_hash,
            "horizons": list(self.horizons),
        }


class FeatureLayer:
    """EvidenceBundle 외의 SQL 접근을 모델에서 금지하는 단일 feature 경계다."""

    definition_version = FEATURE_VERSION
    _definition = {
        "columns": list(FEATURE_COLUMNS),
        "macro_series": list(MACRO_SERIES),
        "required_bars": REQUIRED_BARS,
        "horizons": list(HORIZONS),
        "missing_suffix": MISSING_SUFFIX,
        "macro_note": "latest completed market-state observation per series; unavailable in historical replay",
        "news_social_historical": "off",
    }
    definition_hash = hashlib.sha256(canonical_json(_definition).encode("utf-8")).hexdigest()

    def build(
        self,
        bundle: EvidenceBundle,
        *,
        valuation: Mapping[str, Any] | None = None,
    ) -> FeatureBundle:
        values: dict[str, float | None] = {name: None for name in OPTIONAL_FEATURES}
        values["evidence_domain_count"] = float(len({item.domain for item in bundle.evidence}))
        values["missing_domain_count"] = float(len(bundle.missing_data))
        sources: list[str] = []
        available: list[datetime] = []
        domains: list[str] = []
        for item in bundle.evidence:
            sources.append(item.evidence_id)
            available.append(parse_datetime(item.available_at))
            domains.append(item.domain)
            payload = item.payload
            if item.domain == "market":
                bars = payload.get("latest_bars") if isinstance(payload, Mapping) else None
                values.update(_close_returns(bars if isinstance(bars, list) else []))
            elif item.domain == "technical" and isinstance(payload, Mapping):
                values.update(_technical(payload))
            elif item.domain == "fundamentals" and isinstance(payload, Mapping):
                values.update(_fundamental(payload))
            elif item.domain == "macro" and isinstance(payload, Mapping):
                values.update(_macro(payload))
            elif item.domain == "gurus" and isinstance(payload, Mapping):
                values.update(_gurus(payload))
        as_of = parse_datetime(bundle.as_of_at)
        if any(point > as_of for point in available):
            raise RLSafetyError("EvidenceBundle contains a feature unavailable at as_of_at")
        values.update(_valuation(valuation, as_of=as_of))
        snapshot = FeatureSnapshot(
            feature_version=self.definition_version,
            as_of_at=as_of.isoformat(),
            ticker=bundle.ticker,
            available_at=max(available, default=as_of).isoformat(),
            is_available=bool(sources),
            features=self._normalize(values),
            source_ids=tuple(sources or [f"missing:{bundle.ticker}:{as_of.isoformat()}"]),
            provenance={
                "definition_hash": self.definition_hash,
                "source_kind": bundle.source_kind,
                "domains": sorted(set(domains)),
                "news_social_enabled": bundle.source_kind == "live_shadow",
            },
        )
        return FeatureBundle(snapshot, self.definition_version, self.definition_hash)

    @staticmethod
    def _normalize(values: Mapping[str, float | None]) -> dict[str, float | None]:
        """도메인 유무와 무관하게 항상 같은 컬럼 집합을 만든다.

        결측을 여기서 0으로 채우지 않는다 — RSI 0은 극도 과매도라는 실제 값이라
        관측 없음과 구별되지 않게 된다. 원장에는 None을 그대로 남기고, 학습 행렬을
        만들 때 impute_cross_section()이 대체값과 지표를 함께 넣는다.
        """
        normalized: dict[str, float | None] = {}
        for name in ALWAYS_KNOWN_FEATURES:
            value = values.get(name)
            if value is None:
                raise RLSafetyError(f"always-known feature is missing: {name}")
            normalized[name] = float(value)
        for name in OPTIONAL_FEATURES:
            value = values.get(name)
            normalized[name] = None if value is None else float(value)
            normalized[f"{name}{MISSING_SUFFIX}"] = 0.0 if value is not None else 1.0
        return normalized

    @staticmethod
    def forward_label(
        *,
        feature_version: str,
        as_of_at: str,
        ticker: str,
        horizon_days: int,
        current_close: float,
        forward_close: float,
        benchmark_current_close: float,
        benchmark_forward_close: float,
        forward_end_at: str,
        benchmark_forward_end_at: str,
        label_available_at: str | None = None,
    ) -> ForwardReturnLabel:
        """단일 horizon label을 구간 종료가 확정된 뒤에만 만든다.

        `label_available_at`을 넘기면 실제 적재 시각을 근거로 쓴다. 생략하면 구간
        종료 시각을 그대로 쓰며, 어느 쪽이든 계약이 `>= forward_end_at`을 검사한다.
        """
        if horizon_days not in HORIZONS:
            raise ValueError(f"horizon_days must be one of {HORIZONS}")
        if current_close <= 0 or benchmark_current_close <= 0:
            raise ValueError("current close values must be positive")
        if parse_datetime(forward_end_at) != parse_datetime(benchmark_forward_end_at):
            raise RLSafetyError("asset and benchmark label endpoints must match")
        return ForwardReturnLabel(
            feature_version=feature_version,
            as_of_at=as_of_at,
            ticker=ticker,
            forward_end_at=forward_end_at,
            label_available_at=label_available_at or forward_end_at,
            forward_return=float(forward_close) / current_close - 1.0,
            benchmark_forward_return=float(benchmark_forward_close) / benchmark_current_close - 1.0,
        )

    @staticmethod
    def labels(
        snapshot: FeatureSnapshot,
        *,
        future_closes: Mapping[int, tuple[str, float]],
        benchmark_closes: Mapping[int, tuple[str, float]],
        current_close: float,
        benchmark_current_close: float,
    ) -> tuple[ForwardReturnLabel, ...]:
        """1/5/20 거래일 종료 뒤에만 label을 생성한다."""
        if current_close <= 0 or benchmark_current_close <= 0:
            raise ValueError("current close values must be positive")
        labels: list[ForwardReturnLabel] = []
        for horizon in HORIZONS:
            if horizon not in future_closes or horizon not in benchmark_closes:
                raise RLSafetyError(f"missing {horizon} trading-day label endpoint")
            end_at, close = future_closes[horizon]
            benchmark_end_at, benchmark_close = benchmark_closes[horizon]
            labels.append(FeatureLayer.forward_label(
                feature_version=snapshot.feature_version,
                as_of_at=snapshot.as_of_at,
                ticker=snapshot.ticker,
                horizon_days=horizon,
                current_close=current_close,
                forward_close=close,
                benchmark_current_close=benchmark_current_close,
                benchmark_forward_close=benchmark_close,
                forward_end_at=end_at,
                benchmark_forward_end_at=benchmark_end_at,
            ))
        return tuple(labels)


def impute_cross_section(
    snapshots: Sequence[FeatureSnapshot],
    *,
    fallback: float = 0.0,
) -> list[dict[str, float]]:
    """같은 시점 종목들의 중앙값으로 결측을 채워 유한한 학습 행렬을 만든다.

    원장(rl_feature_snapshots)에는 None을 그대로 보존하고 학습 직전에만 통과시킨다.
    `<name>__is_missing`이 1.0으로 남아 있으므로 모델은 대체값과 관측값을 구별할 수
    있다. 한 컬럼이 그 시점 전 종목에서 결측이면 대체할 근거가 없어 fallback을 쓴다.
    """
    if not snapshots:
        return []
    known: dict[str, list[float]] = {name: [] for name in OPTIONAL_FEATURES}
    for snapshot in snapshots:
        for name in OPTIONAL_FEATURES:
            value = snapshot.features.get(name)
            if value is not None:
                known[name].append(float(value))
    medians = {
        name: (statistics.median(values) if values else float(fallback))
        for name, values in known.items()
    }
    rows: list[dict[str, float]] = []
    for snapshot in snapshots:
        row: dict[str, float] = {}
        for name in ALWAYS_KNOWN_FEATURES:
            row[name] = float(snapshot.features[name])
        for name in OPTIONAL_FEATURES:
            value = snapshot.features.get(name)
            row[name] = medians[name] if value is None else float(value)
            row[f"{name}{MISSING_SUFFIX}"] = float(
                snapshot.features.get(f"{name}{MISSING_SUFFIX}", 1.0 if value is None else 0.0)
            )
        rows.append(row)
    return rows


__all__ = [
    "ALWAYS_KNOWN_FEATURES",
    "FEATURE_COLUMNS",
    "FEATURE_VERSION",
    "HORIZONS",
    "MACRO_SERIES",
    "MISSING_SUFFIX",
    "OPTIONAL_FEATURES",
    "REQUIRED_BARS",
    "FeatureBundle",
    "FeatureLayer",
    "impute_cross_section",
]
