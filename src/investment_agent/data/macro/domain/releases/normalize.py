"""ECON raw observation을 투자용 measure로 정규화하는 순수 로직.

family 하나의 raw series에서 필요한 LEVEL/MoM/YoY/change measure만 계산한다.
예상·실제 비교는 반드시 같은 measure_id에서만 하므로 raw index와 MoM forecast를
비교하는 경로가 이 모듈 밖으로 새지 않게 한다.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any


class MeasureValidationError(ValueError):
    """raw 또는 measure 계약이 유효하지 않을 때 발생한다."""


def finite(value: Any) -> float:
    """유한한 숫자만 DB 입력값으로 허용한다."""
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise MeasureValidationError("value must be numeric") from exc
    if not math.isfinite(result):
        raise MeasureValidationError("value must be finite")
    return result


def _previous_observation(sorted_periods: list[date], current: date, lag: int) -> date | None:
    """주간·불규칙 시계열용 직전 N번째 관측기간을 반환한다."""
    try:
        index = sorted_periods.index(current)
    except ValueError:
        return None
    return sorted_periods[index - lag] if index >= lag else None


def calendar_months_before(current: date, months: int) -> date:
    """외부 의존성 없이 달력상 정확히 N개월 전의 같은 기준일을 계산한다."""
    month_index = current.year * 12 + current.month - 1 - months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    # ECON 월/분기 기준기간은 통상 1일이다. 혹시 월말 기준값이 들어와도
    # 잘못된 날짜를 만들지 않도록 대상 월의 마지막 날로 제한한다.
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - date.resolution).day
    return date(year, month, min(current.day, last_day))


def _lag_period(
    measure: Mapping[str, Any],
    *,
    periods: list[date],
    current: date,
    lag: int,
) -> date | None:
    """transform 의미에 맞는 기저기간을 고른다."""
    transform = str(measure["transform"])
    if transform == "change_previous":
        return _previous_observation(periods, current, lag)
    frequency = str(measure.get("frequency") or "monthly")
    if frequency == "weekly":
        return current - timedelta(days=7 * lag)
    if frequency in {"daily", "irregular"}:
        return current - timedelta(days=lag)
    return calendar_months_before(current, lag * (3 if frequency == "quarterly" else 1))


def required_history_start(
    measures: Iterable[Mapping[str, Any]], *, frequency: str, ref_period: date,
) -> date:
    """현재 발표와 함께 개정될 수 있는 비교기간까지 한 번의 API 요청에 포함한다."""
    lags = {"change_1": 1, "change_previous": 1, "pct_change_1": 1,
            "change_4": 4, "pct_change_12": 12}
    lag = max((lags.get(str(row["transform"]), 0) for row in measures), default=0)
    if frequency in {"monthly", "quarterly"}:
        return calendar_months_before(ref_period, lag * (3 if frequency == "quarterly" else 1))
    # 주간 발표일이 휴일로 이동해도 직전 관측을 함께 가져오도록 한 주를 더 읽는다.
    return ref_period - timedelta(days=(lag + 1) * 7 if frequency == "weekly" else lag)


def calculate_measure(
    transform: str,
    *,
    current: float,
    prior_1: float | None = None,
    prior_4: float | None = None,
    prior_12: float | None = None,
) -> float | None:
    """하나의 measure transform을 계산한다."""
    current = finite(current)
    if transform == "level":
        return current
    if transform in {"change_1", "change_previous"}:
        return None if prior_1 is None else current - finite(prior_1)
    if transform == "change_4":
        return None if prior_4 is None else current - finite(prior_4)
    if transform == "pct_change_1":
        return _percentage_change(current, prior_1)
    if transform == "pct_change_12":
        return _percentage_change(current, prior_12)
    raise MeasureValidationError(f"unsupported transform: {transform}")


def _percentage_change(current: float, prior: float | None) -> float | None:
    if prior is None:
        return None
    base = finite(prior)
    if base == 0:
        return None
    return (current / base - 1.0) * 100.0


def calculate_family(
    measures: Iterable[Mapping[str, Any]],
    raw_by_period: Mapping[date, float],
) -> dict[date, dict[str, float]]:
    """latest raw history를 measure별 값으로 계산한다.

    반환에는 충분한 선행 관측이 없는 변화율 measure를 넣지 않는다. 0을 추정값으로
    저장하지 않는 fail-closed 규칙이다.
    """
    checked = {period: finite(value) for period, value in raw_by_period.items()}
    periods = sorted(checked)
    output: dict[date, dict[str, float]] = {}
    for period in periods:
        current = checked[period]
        values: dict[str, float] = {}
        for measure in measures:
            transform = str(measure["transform"])
            prior_1 = _lag_period(measure, periods=periods, current=period, lag=1)
            prior_4 = _lag_period(measure, periods=periods, current=period, lag=4)
            prior_12 = _lag_period(measure, periods=periods, current=period, lag=12)
            result = calculate_measure(
                transform,
                current=current,
                prior_1=_value(checked, prior_1),
                prior_4=_value(checked, prior_4),
                prior_12=_value(checked, prior_12),
            )
            if result is not None:
                values[str(measure["measure_id"])] = finite(result)
        if values:
            output[period] = values
    return output


def _value(values: Mapping[date, float], period: date | None) -> float | None:
    return None if period is None else values.get(period)
