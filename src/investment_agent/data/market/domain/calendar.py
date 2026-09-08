"""미국 시장의 시간 규칙.

## 왜 platform이 아니라 여기인가

"장이 언제 끝나는가"는 시장 도메인 지식이다. `platform/clock.py`는 "지금이 언제이고
이 값이 어느 시간대인가"까지만 안다. 시장 시간 규칙은 이 모듈이 소유한다.

## 확정되지 않은 봉을 받지 않는다

yfinance는 **장중에도** 오늘 날짜의 일봉을 준다. 그 값은 종가가 아니라 현재가이고,
장이 끝나면 달라진다. 그것을 그대로 적재하면 예외 없이 틀린 종가가 들어가고, 다음날
덮어쓰기 전까지 모든 계산이 그 값을 쓴다.

그래서 **뉴욕 18:00 이전에는 오늘을 받지 않는다.** 18:00인 이유는 장 마감(16:00) 뒤에도
소스가 값을 손보는 일이 흔하기 때문이다.

## 휴장 달력을 내장하지 않는다

주말·공휴일에는 소스가 애초에 봉을 주지 않는다. 여기서 계산하는 것은 **상한**이므로
휴장일을 알 필요가 없고, 달력을 들고 있으면 그것이 낡는 순간 조용히 틀린다.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from investment_agent.platform.clock import ensure_aware, utc_now

MARKET_TIMEZONE = ZoneInfo("America/New_York")

# 이 시각 이후의 일봉만 확정된 것으로 본다(뉴욕 기준).
DAILY_BAR_FINALIZED_AT = time(18, 0)

# 정규장. 8-K 접수 시각이 이 경계로 갈려 실적 감시 창을 정한다.
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)


def market_today(now: datetime | None = None) -> date:
    """시장이 보는 오늘 날짜.

    UTC 자정 근처에서 한국 시각과 뉴욕 날짜가 하루 어긋나므로, 날짜가 필요한
    자리에서는 반드시 이것을 쓴다.
    """
    return ensure_aware(now or utc_now()).astimezone(MARKET_TIMEZONE).date()


def completed_bar_cutoff(now: datetime | None = None) -> date:
    """확정된 일봉의 **상한 날짜**. 이 날짜까지만 적재한다."""
    local = ensure_aware(now or utc_now()).astimezone(MARKET_TIMEZONE)
    cutoff = local.date()
    if local.time().replace(tzinfo=None) < DAILY_BAR_FINALIZED_AT:
        cutoff -= timedelta(days=1)
    return cutoff


def session_of(moment: datetime) -> str:
    """그 시각이 장전(bmo)·장중(dmh)·장후(amc) 중 어디인가.

    실적은 장전 06:00~09:30, 장후 16:00~17:30에 몰려 나오고 그 사이가 8시간 넘게
    벌어진다. 감시 창을 하나로 잡으면 절반은 늦고 절반은 헛돈다.
    """
    local = ensure_aware(moment).astimezone(MARKET_TIMEZONE).time().replace(tzinfo=None)
    if local < REGULAR_OPEN:
        return "bmo"
    if local < REGULAR_CLOSE:
        return "dmh"
    return "amc"


def overlap_window(days: int, now: datetime | None = None) -> tuple[date, date]:
    """증분 수집이 훑을 구간. 끝은 확정 상한이고, 앞으로 `days`일 겹쳐 본다.

    겹쳐 보는 이유는 소스가 과거 봉을 조용히 고치기 때문이다. 마지막 적재일 다음날부터만
    읽으면 그 수정이 영영 안 들어온다.
    """
    if days < 1:
        raise ValueError("days must be >= 1")
    end = completed_bar_cutoff(now)
    return end - timedelta(days=days - 1), end


__all__ = [
    "DAILY_BAR_FINALIZED_AT",
    "MARKET_TIMEZONE",
    "REGULAR_CLOSE",
    "REGULAR_OPEN",
    "completed_bar_cutoff",
    "market_today",
    "overlap_window",
    "session_of",
]
