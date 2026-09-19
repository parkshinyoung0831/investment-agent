"""중장기 선별 factor 점수: 같은 시점 종목들 사이의 순위로 품질·건전성·성장·가치·기대·모멘텀을 잰다.

## 왜 순위(백분위)인가

ROE 30%와 FCF수익률 5%는 단위가 달라 더할 수 없고, 극단값 하나가 평균을 끌고 간다. 같은 날 전체
종목 안에서의 백분위로 바꾸면 factor끼리 더할 수 있고 이상치에 강하다. 값이 없는 종목은 그 factor에서
빠질 뿐 0점을 받지 않는다 — 결측을 나쁜 값으로 읽으면 공시가 늦은 종목이 체계적으로 밀린다.

## 가중치는 정답이 아니다

category 가중치는 기본 동일가중이다. 어느 factor가 이 유니버스에서 실제로 앞으로의 초과수익을 설명하는지는
`research.commands.factor_research`가 과거 재현 시점들의 IC로 잰다. 그 결과로 가중치를 바꾸되, 바꾼 값은
`FactorModel`의 버전과 함께 기록한다.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

# (feature 이름, 방향). 방향 -1은 값이 작을수록 좋다.
FACTOR_CATEGORIES: dict[str, tuple[tuple[str, int], ...]] = {
    "quality": (
        ("quality_roe_ttm", 1),
        ("quality_roa_ttm", 1),
        ("quality_gross_margin_ttm", 1),
        ("quality_fcf_margin_ttm", 1),
        ("quality_accruals_ttm", -1),
        ("quality_operating_margin_volatility", -1),
    ),
    "balance_sheet": (
        ("quality_interest_coverage_ttm", 1),
        ("quality_debt_to_equity", -1),
    ),
    "growth": (
        ("growth_revenue_ttm_yoy", 1),
        ("fundamental_net_income_growth", 1),
    ),
    "value": (
        ("valuation_earnings_yield", 1),
        ("valuation_fcf_yield", 1),
        ("valuation_ps_ttm", -1),
    ),
    "revision": (
        ("revision_breadth_30d", 1),
        ("revision_eps_change", 1),
    ),
    "momentum": (
        ("momentum_12_1", 1),
        ("momentum_6_1", 1),
    ),
}
# 가치 비교는 업종 안에서 한다. 은행의 PSR과 소프트웨어의 PSR을 한 줄로 세우면 업종 선택이 되고 만다.
SECTOR_RELATIVE_CATEGORIES = frozenset({"value"})
# 한 category에서 이 비율 이상의 factor가 있어야 점수를 준다. 하나만으로 category를 대표하게 두지 않는다.
_MIN_CATEGORY_COVERAGE = 0.5
# 업종 안 순위를 매길 최소 종목 수. 이보다 적으면 전체 유니버스 순위를 쓴다.
_MIN_GROUP_SIZE = 5


@dataclass(frozen=True)
class FactorModel:
    """category 가중치와 품질 기준. 버전은 가중치를 바꿀 때마다 올린다."""

    version: str = "factor-v1-equal"
    weights: Mapping[str, float] = field(default_factory=lambda: {name: 1.0 for name in FACTOR_CATEGORIES})
    # 보유 후보가 되려면 품질·재무건전성이 유니버스 하위 이 백분위보다 높아야 한다. 초기값이다.
    quality_floor: float = 0.3
    balance_sheet_floor: float = 0.2

    def __post_init__(self) -> None:
        unknown = set(self.weights) - set(FACTOR_CATEGORIES)
        if unknown:
            raise ValueError(f"unknown factor categories: {sorted(unknown)}")
        if any(not math.isfinite(value) or value < 0 for value in self.weights.values()):
            raise ValueError("factor weights must be finite and non-negative")
        if not any(value > 0 for value in self.weights.values()):
            raise ValueError("at least one factor weight must be positive")
        for name in ("quality_floor", "balance_sheet_floor"):
            if not 0.0 <= getattr(self, name) < 1.0:
                raise ValueError(f"{name} must be in [0, 1)")


def load_factor_model_from_ic_report(
    path: Path | str,
    *,
    horizon: int,
    version: str,
) -> FactorModel:
    """IC 연구 산출물의 특정 기간 제안을 명시적인 새 모델 버전으로 읽는다.

    기간과 버전을 호출자가 반드시 고르게 해 `latest.json`이 바뀌었다는 이유만으로 운영 기본 모델이
    조용히 바뀌지 않게 한다. 기본 `FactorModel()`은 계속 동일가중 v1이다.
    """
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    suggestions = report.get("suggested_weights_by_horizon") or {}
    selected = suggestions.get(str(horizon))
    if not isinstance(selected, Mapping):
        raise ValueError(f"IC report has no suggested weights for horizon {horizon}")
    weights = selected.get("weights")
    if not isinstance(weights, Mapping):
        raise ValueError(f"IC report weights are invalid for horizon {horizon}")
    return FactorModel(version=version, weights={str(name): float(value) for name, value in weights.items()})


@dataclass(frozen=True)
class FactorScore:
    ticker: str
    category_scores: Mapping[str, float]
    composite: float | None
    passes_quality_gate: bool
    gate_reason: str | None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "category_scores": {name: round(value, 6) for name, value in sorted(self.category_scores.items())},
            "composite": None if self.composite is None else round(self.composite, 6),
            "passes_quality_gate": self.passes_quality_gate,
            "gate_reason": self.gate_reason,
        }


def percentile_ranks(values: Mapping[str, float | None]) -> dict[str, float]:
    """값이 있는 종목만 0~1 백분위. 동률은 평균 순위. 한 종목뿐이면 가운데(0.5)."""
    known = sorted(((ticker, float(value)) for ticker, value in values.items()
                    if value is not None and math.isfinite(float(value))), key=lambda item: item[1])
    if not known:
        return {}
    if len(known) == 1:
        return {known[0][0]: 0.5}
    ranks: dict[str, float] = {}
    index = 0
    while index < len(known):
        end = index
        while end + 1 < len(known) and known[end + 1][1] == known[index][1]:
            end += 1
        average = (index + end) / 2
        for position in range(index, end + 1):
            ranks[known[position][0]] = average / (len(known) - 1)
        index = end + 1
    return ranks


def _factor_ranks(
    features: Mapping[str, Mapping[str, float | None]],
    name: str,
    *,
    groups: Mapping[str, str] | None,
) -> dict[str, float]:
    values = {ticker: row.get(name) for ticker, row in features.items()}
    if not groups:
        return percentile_ranks(values)
    by_group: dict[str, dict[str, float | None]] = {}
    for ticker, value in values.items():
        by_group.setdefault(groups.get(ticker, "_unknown"), {})[ticker] = value
    universe = percentile_ranks(values)
    ranks: dict[str, float] = {}
    for members in by_group.values():
        known = sum(1 for value in members.values() if value is not None)
        local = percentile_ranks(members) if known >= _MIN_GROUP_SIZE else {
            ticker: universe[ticker] for ticker in members if ticker in universe
        }
        ranks.update(local)
    return ranks


def score_cross_section(
    features: Mapping[str, Mapping[str, float | None]],
    *,
    model: FactorModel | None = None,
    groups: Mapping[str, str] | None = None,
) -> dict[str, FactorScore]:
    """같은 시점 종목들의 feature로 category 점수·종합 점수·품질 기준 통과 여부를 계산한다."""
    selected = model or FactorModel()
    category_scores: dict[str, dict[str, float]] = {ticker: {} for ticker in features}
    for category, members in FACTOR_CATEGORIES.items():
        ranked = {
            name: _factor_ranks(features, name, groups=groups if category in SECTOR_RELATIVE_CATEGORIES else None)
            for name, _direction in members
        }
        for ticker in features:
            parts = [
                ranked[name][ticker] if direction > 0 else 1.0 - ranked[name][ticker]
                for name, direction in members if ticker in ranked[name]
            ]
            if parts and len(parts) / len(members) >= _MIN_CATEGORY_COVERAGE:
                category_scores[ticker][category] = math.fsum(parts) / len(parts)
    output: dict[str, FactorScore] = {}
    for ticker, scores in category_scores.items():
        weighted = [(selected.weights.get(name, 0.0), value) for name, value in scores.items()
                    if selected.weights.get(name, 0.0) > 0]
        weight_sum = math.fsum(weight for weight, _ in weighted)
        composite = math.fsum(weight * value for weight, value in weighted) / weight_sum if weight_sum > 0 else None
        reason = None
        if "quality" not in scores:
            reason = "quality_unknown"
        elif scores["quality"] < selected.quality_floor:
            reason = "quality_below_floor"
        elif scores.get("balance_sheet") is not None and scores["balance_sheet"] < selected.balance_sheet_floor:
            reason = "balance_sheet_below_floor"
        output[ticker] = FactorScore(ticker, scores, composite, reason is None, reason)
    return output


def rank_candidates(scores: Mapping[str, FactorScore], *, limit: int) -> list[FactorScore]:
    """품질 기준을 통과한 종목 중 종합 점수 순. 점수가 같으면 ticker 순으로 결정적으로 자른다."""
    if limit < 1:
        raise ValueError("limit must be positive")
    eligible = [score for score in scores.values() if score.passes_quality_gate and score.composite is not None]
    eligible.sort(key=lambda score: (-float(score.composite), score.ticker))
    return eligible[:limit]


def feature_rows_by_ticker(rows: Sequence[Mapping]) -> dict[str, Mapping[str, float | None]]:
    """snapshot 저장 행들을 ticker → feature dict로. 같은 ticker가 여럿이면 마지막 행을 쓴다."""
    return {str(row["ticker"]).upper(): dict(row.get("features") or {}) for row in rows}


def latest_cross_section(
    rows: Sequence[Mapping],
    *,
    feature_version: str,
    min_coverage: int,
) -> tuple[str, dict[str, Mapping[str, float | None]]] | None:
    """판단 시각이 가장 최근이면서 종목 수가 `min_coverage` 이상인 한 시점의 feature 횡단면.

    feature 적재가 중간에 끊긴 날은 종목이 일부뿐이라 백분위가 그 일부 안의 순위가 된다. 그런 날은
    건너뛰고 직전의 온전한 날을 쓴다. 다른 feature 세대와 섞지 않는다.
    """
    by_as_of: dict[str, dict[str, Mapping[str, float | None]]] = {}
    for row in rows:
        if str(row.get("feature_version")) != feature_version or not row.get("is_available", True):
            continue
        by_as_of.setdefault(str(row["as_of_at"]), {})[str(row["ticker"]).upper()] = dict(row.get("features") or {})
    for as_of in sorted(by_as_of, reverse=True):
        if len(by_as_of[as_of]) >= min_coverage:
            return as_of, by_as_of[as_of]
    return None


__all__ = [
    "latest_cross_section",
    "FACTOR_CATEGORIES",
    "SECTOR_RELATIVE_CATEGORIES",
    "FactorModel",
    "FactorScore",
    "feature_rows_by_ticker",
    "load_factor_model_from_ic_report",
    "percentile_ranks",
    "rank_candidates",
    "score_cross_section",
]
