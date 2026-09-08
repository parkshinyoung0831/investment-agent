"""ECON release schedule의 timezone·reference period·rule 계산.

DB의 releases.scheduled_at가 유일한 scheduler SSOT다. 이 모듈은 source에서 받은
날짜와 명시적인 release timezone/time을 UTC로 바꾸기만 하며, UTC 기본 08:30 같은
숨은 fallback을 절대 사용하지 않는다.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


class ScheduleContractError(ValueError):
    """schedule source contract가 불완전하거나 모순될 때 발생한다."""


UTC = timezone.utc
_DATE_ONLY_TIME = time(12, 0)

# official BOK Monetary Policy Board calendar에서 전사한 현재 운영 범위의 날짜.
# 이 목록은 추정 rule이 아니며 매년 official calendar 갱신이 없으면 해당 family는
# degraded로 보고한다. 09:50 KST는 source contract와 이 함수가 함께 강제한다.
_KR_BASE_RATE_DATES: tuple[date, ...] = (
    date(2026, 1, 15), date(2026, 2, 26), date(2026, 4, 16),
    date(2026, 5, 28), date(2026, 7, 16), date(2026, 8, 27),
    date(2026, 10, 15), date(2026, 11, 26),
)

# 발표일이 대표하는 관측 월과의 간격. 기본은 1개월이고, 다른 것만 적는다.
# 값은 ALFRED vintage로 확인한다 — vintage 날짜와 그 시점의 최신 관측 월 차이가 곧 lag다.
# 틀리면 지나간 기간에 미래 발표일이 붙고, 실제값이 도착할 때
# releases.release_schedule_before_first_actual CHECK가 daily 전체를 실패시킨다.
_MONTH_LAG = {
    "US_JOLTS_OPENINGS": 2,
    "US_MICHIGAN_SENTIMENT": 0,
}
_WEEKLY_LAG_DAYS = {
    "US_INITIAL_CLAIMS": 5,
    "US_CONTINUING_CLAIMS": 5,
    "EIA_CRUDE_OIL_INVENTORIES": 5,
}


def scheduled_at_utc(
    scheduled_date: date,
    *,
    release_time: str | None,
    release_tz: str,
    confidence: str,
) -> datetime:
    """로컬 발표일시를 DST를 반영한 UTC datetime으로 만든다.

    date_only는 거짓 precision을 만들지 않기 위해 현지 정오를 storage anchor로 쓴다.
    watcher는 confidence별 넓은 window를 사용하므로 이 anchor를 정확 시각으로 해석하지
    않는다.
    """
    try:
        zone = ZoneInfo(release_tz)
    except Exception as exc:
        raise ScheduleContractError(f"invalid release timezone: {release_tz}") from exc
    if confidence == "date_only":
        local_time = _DATE_ONLY_TIME
    else:
        if not release_time:
            raise ScheduleContractError(
                f"{confidence} schedule requires a source-provided release_time"
            )
        try:
            hours, minutes = (int(part) for part in release_time.split(":", 1))
            local_time = time(hours, minutes)
        except (TypeError, ValueError) as exc:
            raise ScheduleContractError(f"invalid release time: {release_time}") from exc
    return datetime.combine(scheduled_date, local_time, tzinfo=zone).astimezone(UTC)


def schedule_window(confidence: str) -> timedelta:
    """정확도별 watcher 허용 창. API row가 발표시각에 즉시 생긴다고 가정하지 않는다."""
    windows = {
        "exact": timedelta(hours=2),
        "estimated": timedelta(hours=6),
        "rule": timedelta(hours=12),
        "date_only": timedelta(hours=36),
    }
    try:
        return windows[confidence]
    except KeyError as exc:
        raise ScheduleContractError(f"unsupported schedule confidence: {confidence}") from exc


def reference_period(series_id: str, frequency: str, release_date: date) -> date:
    """initial release가 대표하는 raw observation period의 보수적 추정.

    이 값은 release identity와 forecast 결합에만 쓰인다. watcher는 이 period 주변의
    raw observation만 인정해 오래된 직전값을 새 actual로 저장하지 않는다.
    """
    if frequency == "monthly":
        return _month_start(_add_months(release_date, -_MONTH_LAG.get(series_id, 1)))
    if frequency == "quarterly":
        # BEA GDP has advance/second/third releases in Apr/May/Jun for the
        # same Q1 (and equivalently in each following quarter). All three must
        # resolve to one event identity so later values append as revisions.
        if series_id == "US_GDP":
            return _quarter_start(_add_months(release_date, -3))
        return _quarter_start(_add_months(release_date, -1))
    if frequency == "weekly":
        if series_id == "FED_NET_LIQUIDITY":
            return release_date - timedelta(days=1)  # H.4.1 Wednesday balance date.
        return release_date - timedelta(days=_WEEKLY_LAG_DAYS.get(series_id, 0))
    return release_date


def rule_dates(rule: str, *, start: date, end: date) -> list[date]:
    """허용한 공개 schedule rule만 확장한다."""
    if start > end:
        raise ScheduleContractError("schedule range start must not exceed end")
    if rule == "monthly_first_business_day":
        return [
            day for day in (_first_business_day(year, month) for year, month in _months(start, end))
            if start <= day <= end
        ]
    if rule == "weekly_wednesday":
        offset = (2 - start.weekday()) % 7
        first = start + timedelta(days=offset)
        return [first + timedelta(days=7 * step) for step in range(((end - first).days // 7) + 1)]
    if rule == "quarterly_advance_estimate":
        # 일정 source가 정확한 공개 datetime을 주지 않아 date_only anchor를 쓴다.
        return [
            date(year, month, 25)
            for year, month in _months(start, end)
            if month in {1, 4, 7, 10} and start <= date(year, month, 25) <= end
        ]
    raise ScheduleContractError(f"unsupported schedule rule: {rule}")


def official_calendar_dates(series_id: str, *, start: date, end: date) -> list[date]:
    """scraping 없이 DB 저장이 허가된 공식 일정만 반환한다."""
    if series_id == "KR_BASE_RATE":
        return [day for day in _KR_BASE_RATE_DATES if start <= day <= end]
    raise ScheduleContractError(f"no official calendar seed for {series_id}")


def release_row(setting: dict[str, Any], scheduled_date: date, *, schedule_source: str) -> dict[str, Any]:
    """source contract 한 건을 releases upsert payload로 바꾼다."""
    contract = setting.get("source_contract") or {}
    schedule = contract.get("schedule") or {}
    confidence = str(schedule.get("confidence") or "")
    timezone_name = str(schedule.get("timezone") or "")
    if not confidence or not timezone_name:
        raise ScheduleContractError(f"{setting['series_id']}: incomplete schedule contract")
    when = scheduled_at_utc(
        scheduled_date,
        release_time=schedule.get("time"),
        release_tz=timezone_name,
        confidence=confidence,
    )
    return {
        "series_id": str(setting["series_id"]),
        "ref_period": reference_period(
            str(setting["series_id"]), str(setting["frequency"]), scheduled_date
        ).isoformat(),
        "scheduled_at": when.isoformat(),
        "schedule_source": schedule_source,
        "schedule_confidence": confidence,
        "status": "scheduled",
        "provenance": {
            "schedule": {
                "source": schedule_source,
                "source_date": scheduled_date.isoformat(),
                "timezone": timezone_name,
                "local_time": schedule.get("time"),
                "confidence": confidence,
            }
        },
    }


def _add_months(day: date, months: int) -> date:
    total = day.year * 12 + day.month - 1 + months
    year, month_zero = divmod(total, 12)
    month = month_zero + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _month_start(day: date) -> date:
    return date(day.year, day.month, 1)


def _quarter_start(day: date) -> date:
    return date(day.year, ((day.month - 1) // 3) * 3 + 1, 1)


def _months(start: date, end: date) -> list[tuple[int, int]]:
    cursor = date(start.year, start.month, 1)
    final = date(end.year, end.month, 1)
    values: list[tuple[int, int]] = []
    while cursor <= final:
        values.append((cursor.year, cursor.month))
        cursor = _add_months(cursor, 1)
    return values


def _first_business_day(year: int, month: int) -> date:
    day = date(year, month, 1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day
