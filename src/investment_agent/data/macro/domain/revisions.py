"""거시 지표의 정정(revision)을 다루는 규칙.

## 발표된 숫자는 나중에 바뀐다

GDP·고용처럼 중요한 지표일수록 여러 번 고쳐진다. 최초 발표(first print)와 최종 수치가
크게 다른 일이 흔하고, **그 차이 자체가 시장을 움직인다.**

그래서 관측을 덮어쓰지 않고 `(series_id, ref_period, effective_at, collected_at)`으로
쌓는다. 여기 있는 함수들이 그 더미에서 "언제 기준의 값"을 골라낸다.

## 세 시각을 구분한다

* `ref_period` — 그 숫자가 **말하는** 기간(2026년 7월 고용).
* `effective_at` — 그 값이 **유효해진** 시각(발표 시각).
* `collected_at` — 우리가 **손에 넣은** 시각.

셋을 섞으면 backtest가 발표 전에 발표 값을 본다. 그 오류는 성적을 좋게 만들기 때문에
아무도 의심하지 않는다.

## 정밀도를 함께 들고 다닌다

발표 시각을 분 단위로 아는 지표가 있고, 날짜만 아는 지표가 있고, 우리가 처음 본 시각
말고는 근거가 없는 지표가 있다. `time_precision`이 그것을 말한다 — 날짜만 아는 값을
분 단위로 취급하면 발표 당일 장중 판단이 조용히 미래를 본다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from investment_agent.platform.clock import as_date, ensure_aware
from investment_agent.platform.serialization import finite_float, parse_datetime

# 값이 언제 유효해졌는지 얼마나 정확히 아는가.
TIME_PRECISIONS = ("exact", "date_only", "collector_seen")

# 날짜만 아는 값은 그날 안의 어느 시각인지 모른다. PIT 조회에서 그 하루를 통째로
# 미룬다 — 발표 당일 장중에 그 값을 알았다고 가정하지 않기 위해서다.
DATE_ONLY_LAG = timedelta(days=1)


class MacroDataError(ValueError):
    """거시 관측이 계약을 어겼다."""


@dataclass(frozen=True)
class Observation:
    """관측 한 버전. 같은 `(series_id, ref_period)`에 여러 개가 있을 수 있다."""

    series_id: str
    ref_period: date
    value: float
    effective_at: datetime
    collected_at: datetime
    time_precision: str = "collector_seen"

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Observation":
        ref_period = as_date(row.get("ref_period"))
        value = finite_float(row.get("value"))
        if ref_period is None:
            raise MacroDataError(f"unreadable ref_period: {row.get('ref_period')!r}")
        if value is None:
            # NaN 하나가 이후 모든 집계를 조용히 NaN으로 만든다.
            raise MacroDataError(f"{row.get('series_id')} {ref_period}: value is not finite")
        precision = str(row.get("time_precision") or "collector_seen")
        if precision not in TIME_PRECISIONS:
            raise MacroDataError(f"unknown time_precision: {precision!r}")
        return cls(
            series_id=str(row["series_id"]),
            ref_period=ref_period,
            value=value,
            effective_at=parse_datetime(row["effective_at"]),
            collected_at=parse_datetime(row["collected_at"]),
            time_precision=precision,
        )

    def known_at(self, as_of: datetime) -> bool:
        """`as_of` 시점에 이 값을 알 수 있었는가.

        **두 경계를 모두 넘어야 한다.** 유효해졌더라도 우리가 아직 손에 넣지 못했으면
        쓸 수 없었다. 둘 중 늦은 쪽이 실제로 알게 된 시각이다.
        """
        moment = max(ensure_aware(self.effective_at), ensure_aware(self.collected_at))
        if self.time_precision == "date_only":
            # 그날 몇 시인지 모르므로 하루를 미룬다. 모르는 것을 유리하게 읽지 않는다.
            moment += DATE_ONLY_LAG
        return moment <= ensure_aware(as_of)


def first_print(observations: Iterable[Observation]) -> Observation | None:
    """최초 발표값. 정정 전 숫자라 서프라이즈 계산의 기준이 된다."""
    ordered = sorted(observations, key=lambda item: (ensure_aware(item.effective_at), item.collected_at))
    return ordered[0] if ordered else None


def latest_known_at(
    observations: Iterable[Observation], as_of: datetime
) -> Observation | None:
    """`as_of` 시점에 알고 있던 것 중 가장 최근에 유효해진 값."""
    known = [item for item in observations if item.known_at(as_of)]
    if not known:
        return None
    return max(known, key=lambda item: (ensure_aware(item.effective_at), item.collected_at))


def series_as_of(
    observations: Iterable[Observation], as_of: datetime
) -> dict[date, float]:
    """그 시점에 보이던 **시계열 전체**. 기간마다 그때의 최신 버전을 고른다.

    기간별로 따로 고르는 것이 핵심이다. 시계열 하나를 통째로 최신 버전으로 채우면
    과거 기간에 나중에 정정된 값이 들어가 학습 데이터가 미래를 본다.
    """
    by_period: dict[date, list[Observation]] = {}
    for item in observations:
        by_period.setdefault(item.ref_period, []).append(item)
    result: dict[date, float] = {}
    for period, versions in by_period.items():
        picked = latest_known_at(versions, as_of)
        if picked is not None:
            result[period] = picked.value
    return result


def revision_size(observations: Sequence[Observation]) -> float | None:
    """최초 발표에서 최종값까지의 변화량. 정정이 없었으면 `None`.

    크게 고쳐지는 지표는 최초 발표를 그대로 믿으면 안 된다는 신호다.
    """
    if len(observations) < 2:
        return None
    first = first_print(observations)
    last = max(observations, key=lambda item: ensure_aware(item.effective_at))
    if first is None or first is last:
        return None
    return last.value - first.value


__all__ = [
    "DATE_ONLY_LAG",
    "MacroDataError",
    "Observation",
    "TIME_PRECISIONS",
    "first_print",
    "latest_known_at",
    "revision_size",
    "series_as_of",
]
