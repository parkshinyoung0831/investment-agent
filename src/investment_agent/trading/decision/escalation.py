"""Deep LLM 재분석을 건너뛰어도 됐을까 — 판정만 기록하는 shadow다. 아무것도 건너뛰지 않는다.

## 왜 건너뛰기가 아니라 "유효기간 연장"인가

논지가 없는 미보유 종목은 편입이 막힌다(`AlphaPolicy.require_verified_entry`). Deep LLM을 건너뛰면
비용이 줄어드는 것이 아니라 그 종목이 그날 편입 후보에서 빠진다. 그래서 건너뛸 수 있는 경우는
"직전 논지가 아직 쓸 만하고 그 뒤로 바뀐 것이 없는 **재분석**"뿐이고, 그때의 동작은 직전 논지의
유효기간을 늘리는 것이다(설계 §55.1).

## 왜 shadow부터인가

틀렸을 때의 비용(놓친 논지 붕괴, 놓친 기회)을 재려면 건너뛰었을 판정과 실제 새 판단을 나란히 봐야
한다. 비싼 쪽(Deep LLM)은 어차피 돈다 — 싼 쪽(이 규칙)만 옆에 붙이면 절감을 잃지 않고 잴 수 있다.
판정은 새 판단을 보기 **전에** 내린다. 결과를 본 뒤에 판정하면 규칙이 결과를 엿본다.

## 모르면 건너뛰지 않는다

직전 판단이 없거나 가격 이력으로 직전 이후의 움직임을 잴 수 없으면 `would_skip=False`다(fail-open).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from investment_agent.platform.serialization import finite_float, parse_datetime

ESCALATION_SHADOW_VERSION = "refresh-shadow-v1"
# 직전 논지를 이 기간까지만 연장할 수 있다. 재분석 주기(28일)의 두 배다.
MAX_VIEW_AGE = timedelta(days=56)
# 직전 이후 가격 움직임이 그 기간 변동성의 이 배수를 넘으면 "바뀐 것이 있다"로 본다.
PRICE_SHOCK_SIGMA = 1.5
_SKIPPABLE_THESES = frozenset({"positive", "neutral"})


@dataclass(frozen=True)
class RefreshShadow:
    would_skip: bool
    reasons: tuple[str, ...]
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {"version": ESCALATION_SHADOW_VERSION, "would_skip": self.would_skip,
                "reasons": list(self.reasons), **dict(self.detail)}


def _move_since(bars_desc: Sequence[Mapping[str, Any]], since: datetime) -> tuple[float, float, int] | None:
    """직전 판단 이후 누적 수익률, 일간 변동성, 경과 거래일 수. 이력이 직전 시점을 덮지 못하면 None."""
    bars = sorted(
        ((str(row.get("trade_date"))[:10], finite_float(row.get("close"))) for row in bars_desc),
        key=lambda item: item[0],
    )
    bars = [(day, close) for day, close in bars if close is not None and close > 0]
    if len(bars) < 3:
        return None
    anchor_day = since.date().isoformat()
    before = [index for index, (day, _) in enumerate(bars) if day <= anchor_day]
    if not before:
        return None
    start = before[-1]
    elapsed = len(bars) - 1 - start
    closes = [close for _, close in bars]
    returns = [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))]
    # 표준편차는 판정하려는 충격 자체에 부풀려진다(하루 +12%가 σ를 키워 자기 자신을 가린다). 중앙 절대편차는
    # 봉 몇 개의 충격에 흔들리지 않는다. 1.4826은 정규분포에서 MAD를 σ로 옮기는 상수다.
    center = _median(returns)
    sigma = 1.4826 * _median([abs(value - center) for value in returns])
    return closes[-1] / closes[start] - 1.0, sigma, elapsed


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0


def refresh_shadow(
    *,
    as_of_at: datetime,
    is_held: bool,
    previous: Mapping[str, Any] | None,
    latest_filed_at: str | None,
    bars_desc: Sequence[Mapping[str, Any]],
) -> RefreshShadow:
    """이 재분석을 건너뛰고 직전 논지를 연장했어도 됐을지. 조건을 모두 만족해야 건너뛴다."""
    reasons: list[str] = []
    if is_held:
        reasons.append("held_position")
    if previous is None:
        return RefreshShadow(False, ("no_previous_view", *reasons))
    previous_at = parse_datetime(str(previous["as_of_at"]))
    age = as_of_at - previous_at
    detail: dict[str, Any] = {"previous_case_key": previous.get("case_key"),
                              "previous_age_days": round(age.total_seconds() / 86400.0, 2)}
    thesis = previous.get("thesis")
    detail["previous_thesis"] = thesis
    if age > MAX_VIEW_AGE:
        reasons.append("previous_view_too_old")
    if thesis not in _SKIPPABLE_THESES or previous.get("hard_constraint") not in (None, "none"):
        reasons.append("previous_thesis_not_extendable")
    if latest_filed_at and parse_datetime(str(latest_filed_at)) > previous_at:
        reasons.append("new_filing_since_previous")
    move = _move_since(bars_desc, previous_at)
    if move is None:
        reasons.append("price_history_does_not_cover_previous")
    else:
        change, sigma, elapsed = move
        limit = PRICE_SHOCK_SIGMA * sigma * math.sqrt(max(1, elapsed))
        detail.update(price_change=round(change, 6), price_change_limit=round(limit, 6), elapsed_bars=elapsed)
        if abs(change) > limit:
            reasons.append("price_shock_since_previous")
    return RefreshShadow(not reasons, tuple(reasons) or ("unchanged_since_previous",), detail)


__all__ = ["ESCALATION_SHADOW_VERSION", "MAX_VIEW_AGE", "PRICE_SHOCK_SIGMA", "RefreshShadow", "refresh_shadow"]
