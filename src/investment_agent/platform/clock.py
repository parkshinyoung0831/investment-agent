"""시간을 다루는 최소 규칙.

## naive datetime을 거부한다

tz 없는 datetime을 받아들이면 그 값은 "어느 시간대인지 아무도 모르는 숫자"가 된다.
UTC로 가정하면 자정 근처에서 날짜가 하루씩 밀리고, 그 오류는 예외를 던지지 않는다 —
스냅샷 날짜가 하루 어긋난 채 조용히 적재된다. 그래서 여기서는 **받는 순간** 막는다.

## 시장 달력은 여기 없다

미국 장 마감 시각, 거래일 여부 같은 것은 시장 도메인 지식이라 `data/market`에 있다.
platform은 "지금이 언제인가"와 "이 값이 어느 시간대인가"까지만 안다.

## now를 인자로 받는다

시간에 의존하는 함수는 `now`를 받는다. 받지 않으면 그 함수는 실행하는 시각에 따라
결과가 달라져 테스트할 수 없고, 자정 경계 버그는 정확히 그런 함수에서 나온다.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

UTC = timezone.utc

# 외부 시장 날짜를 계산할 때만 쓰는 고정 시간대다. 거래일 달력이나 봉 수집 규칙은
# 시장 도메인에 두고, 이 모듈은 시간대 변환 자체만 제공한다.
US_MARKET_TIMEZONE = ZoneInfo("America/New_York")
US_DAILY_BAR_FINALIZATION_TIME = time(18, 0)

# 화면·로그에 사람이 읽는 시각을 적을 때만 쓴다. 저장은 항상 UTC다.
KST = ZoneInfo("Asia/Seoul")


class Clock(Protocol):
    """시간 출처. 테스트가 가짜를 끼울 수 있도록 함수가 아니라 타입으로 둔다."""

    def now(self) -> datetime:  # pragma: no cover - Protocol 선언
        ...


class SystemClock:
    """실제 시계. 항상 tz-aware UTC를 준다."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """멈춘 시계. 테스트가 특정 순간을 재현할 때 쓴다."""

    def __init__(self, instant: datetime) -> None:
        self._instant = ensure_aware(instant)

    def now(self) -> datetime:
        return self._instant


def utc_now() -> datetime:
    """지금(UTC). 시간에 의존하는 로직은 이것을 직접 부르지 말고 `Clock`을 받는다."""
    return datetime.now(UTC)


def ensure_aware(value: datetime) -> datetime:
    """tz-aware UTC로 만든다. naive면 **거부한다** — 추측이 조용한 하루 오차를 낳는다."""
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def to_utc_iso(value: datetime) -> str:
    """저장·전송용 문자열. 항상 UTC로 맞춘 뒤 찍는다."""
    return ensure_aware(value).isoformat()


def as_date(value: date | datetime | str | None) -> date | None:
    """날짜로 읽는다. 읽을 수 없으면 `None` — 여기서 예외를 던지면 한 행 때문에
    배치 전체가 멈춘다. 값이 없다는 사실은 부르는 쪽이 판단한다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def day_window(end: date, days: int) -> tuple[date, date]:
    """`end`를 포함해 뒤로 `days`일. 증분 조회의 겹침 구간을 만들 때 쓴다."""
    if days < 1:
        raise ValueError("days must be >= 1")
    return end - timedelta(days=days - 1), end


def us_market_today(now: datetime | None = None) -> date:
    """뉴욕 시장이 관측하는 날짜를 반환한다."""
    return ensure_aware(now or utc_now()).astimezone(US_MARKET_TIMEZONE).date()


def completed_us_daily_bar_cutoff(now: datetime | None = None) -> date:
    """확정된 미국 일봉의 보수적인 상한 날짜를 반환한다."""
    local = ensure_aware(now or utc_now()).astimezone(US_MARKET_TIMEZONE)
    cutoff = local.date()
    if local.time().replace(tzinfo=None) < US_DAILY_BAR_FINALIZATION_TIME:
        cutoff -= timedelta(days=1)
    return cutoff


__all__ = [
    "Clock",
    "US_DAILY_BAR_FINALIZATION_TIME",
    "US_MARKET_TIMEZONE",
    "FixedClock",
    "KST",
    "SystemClock",
    "UTC",
    "as_date",
    "day_window",
    "completed_us_daily_bar_cutoff",
    "ensure_aware",
    "to_utc_iso",
    "us_market_today",
    "utc_now",
]
