"""미국 정규장 시간표(뉴욕 시간 기준)를 인식하여 하네스 동작 국면과 주기를 계산한다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

from investment_agent.platform.serialization import parse_datetime

NY_TZ = ZoneInfo("America/New_York")

# 운영 주기 기준 상수 (초)
HEARTBEAT_POLL_SECONDS = 15.0
RECONCILIATION_INTERVAL_OPEN_SECONDS = 60.0
RECONCILIATION_INTERVAL_STANDBY_SECONDS = 300.0
RISK_SNAPSHOT_INTERVAL_SECONDS = 300.0
APPROVAL_POLL_SECONDS = 15.0
DEFAULT_ANALYSIS_INTERVAL_SECONDS = 24 * 3600.0


def _easter_sunday(year: int) -> date:
    """그레고리력 부활절(Meeus/Jones/Butcher). Good Friday 계산에 쓴다."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    weekday_offset = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday_offset) // 451
    month, day = divmod(h + weekday_offset - 7 * m + 114, 31)
    return date(year, month, day + 1)


def is_us_market_holiday(d: date) -> bool:
    """미국 증권거래소(NYSE)의 정기 휴장일 여부를 판정한다.

    규칙으로 나오는 정기 휴장만 안다. 1회성 임시 휴장(국장 등)은 알 수 없어 실주문은 브로커 캘린더가
    따로 거른다. 조기 마감은 `us_market_close_time`이 안다.
    """
    month = d.month
    day = d.day
    weekday = d.weekday()

    # 1. New Year's Day (1월 1일, 대체 공휴일 포함).
    #    1월 1일이 토요일이면 NYSE는 직전 금요일(12/31)에 열린다 — 다른 토요일 공휴일과 다른 유일한 예외.
    if month == 1 and day == 1 and weekday < 5:
        return True
    if month == 1 and day == 2 and weekday == 0:
        return True

    # 1-1. Good Friday (부활절 이틀 전 금요일)
    if weekday == 4 and d == _easter_sunday(d.year) - timedelta(days=2):
        return True

    # 2. Martin Luther King Jr. Day (1월 셋째 주 월요일)
    if month == 1 and weekday == 0 and 15 <= day <= 21:
        return True

    # 3. Washington's Birthday / Presidents' Day (2월 셋째 주 월요일)
    if month == 2 and weekday == 0 and 15 <= day <= 21:
        return True

    # 4. Memorial Day (5월 마지막 월요일)
    if month == 5 and weekday == 0 and day >= 25:
        return True

    # 5. Juneteenth National Independence Day (6월 19일, 대체 공휴일 포함)
    if month == 6 and day == 19 and weekday < 5:
        return True
    if month == 6 and day == 20 and weekday == 0:
        return True
    if month == 6 and day == 18 and weekday == 4:
        return True

    # 6. Independence Day (7월 4일, 대체 공휴일 포함)
    if month == 7 and day == 4 and weekday < 5:
        return True
    if month == 7 and day == 5 and weekday == 0:
        return True
    if month == 7 and day == 3 and weekday == 4:
        return True

    # 7. Labor Day (9월 첫째 주 월요일)
    if month == 9 and weekday == 0 and 1 <= day <= 7:
        return True

    # 8. Thanksgiving Day (11월 넷째 주 목요일)
    if month == 11 and weekday == 3 and 22 <= day <= 28:
        return True

    # 9. Christmas Day (12월 25일, 대체 공휴일 포함)
    if month == 12 and day == 25 and weekday < 5:
        return True
    if month == 12 and day == 26 and weekday == 0:
        return True
    if month == 12 and day == 24 and weekday == 4:
        return True

    return False


REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)


def is_early_close_day(d: date) -> bool:
    """NYSE 정규 조기 마감(13:00 ET)일: 추수감사절 다음 금요일, 12/24, 7/3(평일이고 7/4 휴장이 다음 날일 때).

    12/24가 금요일이거나 7/3이 금요일이면 각각 크리스마스·독립기념일의 대체 휴장일이라 조기 마감이 아니라 휴장이다.
    """
    if d.weekday() >= 5 or is_us_market_holiday(d):
        return False
    if d.month == 11 and d.weekday() == 4 and 23 <= d.day <= 29:
        return True
    if d.month == 12 and d.day == 24:
        return True
    return d.month == 7 and d.day == 3


def us_market_close_time(d: date) -> time | None:
    """그 날짜의 정규장 마감 시각(뉴욕 현지). 휴장·주말이면 None."""
    if d.weekday() >= 5 or is_us_market_holiday(d):
        return None
    return EARLY_CLOSE if is_early_close_day(d) else REGULAR_CLOSE


@dataclass(frozen=True)
class SessionWindow:
    """DST를 포함한 뉴욕 현지 시각 기준의 신규 판단 시작 구간이다."""

    start: time = time(9, 40)
    end: time = time(14, 30)

    def __post_init__(self) -> None:
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError("session window times must be naive New York wall times")
        if self.start >= self.end:
            raise ValueError("session start must precede session end")

    def is_open(self, value: datetime) -> bool:
        local = parse_datetime(value).astimezone(NY_TZ)
        close = us_market_close_time(local.date())
        if close is None:
            return False
        # 창의 끝은 정규 마감(16:00)에 대한 상대 위치다(판단 창은 마감 90분 전, 위험 감시 창은 마감 30분 뒤).
        # 조기 마감일에는 그 상대 위치를 지켜 끝을 마감이 앞당겨진 만큼 당긴다.
        early_by = datetime.combine(local.date(), REGULAR_CLOSE) - datetime.combine(local.date(), close)
        end = (datetime.combine(local.date(), self.end) - early_by).time()
        return self.start <= local.time().replace(tzinfo=None) <= end

    def seconds_until_open(self, value: datetime) -> float:
        current = parse_datetime(value).astimezone(NY_TZ)
        candidate = datetime.combine(current.date(), self.start, tzinfo=NY_TZ)
        if current >= candidate:
            candidate += timedelta(days=1)
        while candidate.weekday() >= 5 or is_us_market_holiday(candidate.date()):
            candidate += timedelta(days=1)
        return max(1.0, (candidate.astimezone(timezone.utc) - current.astimezone(timezone.utc)).total_seconds())


class USMarketPhase(str, Enum):
    POST_CLOSE_ANALYSIS = "post_close_analysis"  # 16:00 ~ 19:00 NY: SEC 공시 & AI 종목 분석
    PRE_MARKET_APPROVAL = "pre_market_approval"  # 07:00 ~ 09:30 NY: 센티먼트 반영 & Discord 승인 요청
    REGULAR_TRADING = "regular_trading"          # 09:30 ~ 16:00 NY: Toss 주문 체결 & 리스크 감시
    STANDBY = "standby"                          # 야간 및 주말 대기 모드 (Heartbeat만 유지)


@dataclass(frozen=True)
class MarketPhaseInfo:
    phase: USMarketPhase
    is_weekend: bool
    is_holiday: bool
    is_regular_open: bool
    ny_time: datetime
    suggested_interval_seconds: float
    description: str


def get_us_market_phase(now: datetime | None = None) -> MarketPhaseInfo:
    """현재 뉴욕 시간 기준으로 시장 국면과 권장 하네스 주기를 반환한다."""
    current_utc = now or datetime.now(timezone.utc)
    ny_dt = current_utc.astimezone(NY_TZ)
    ny_time = ny_dt.time()
    weekday = ny_dt.weekday()  # 0: Monday, 4: Friday, 5: Saturday, 6: Sunday

    is_weekend = weekday in (5, 6)
    is_holiday = is_us_market_holiday(ny_dt.date())

    if is_weekend or is_holiday:
        reason = "주말 휴장" if is_weekend else "공휴일 휴장"
        return MarketPhaseInfo(
            phase=USMarketPhase.STANDBY,
            is_weekend=is_weekend,
            is_holiday=is_holiday,
            is_regular_open=False,
            ny_time=ny_dt,
            suggested_interval_seconds=RECONCILIATION_INTERVAL_STANDBY_SECONDS,
            description=f"{reason}: 최소 리소스 대기 모드 (Heartbeat 유지)",
        )

    # 주중 시간대별 판정 (NY Time 기준)
    close = us_market_close_time(ny_dt.date()) or REGULAR_CLOSE
    if time(9, 30) <= ny_time < close:
        # 본장 거래 시간 (09:30 ~ 마감, 조기 마감일은 13:00)
        return MarketPhaseInfo(
            phase=USMarketPhase.REGULAR_TRADING,
            is_weekend=False,
            is_holiday=False,
            is_regular_open=True,
            ny_time=ny_dt,
            suggested_interval_seconds=RECONCILIATION_INTERVAL_OPEN_SECONDS,
            description="미국 정규장 진행 중: 실시간 체결 감시 및 리스크 모니터링",
        )
    elif close <= ny_time < time(19, 0):
        # 장마감 직후 공시 및 분석 시간 (마감 ~ 19:00)
        return MarketPhaseInfo(
            phase=USMarketPhase.POST_CLOSE_ANALYSIS,
            is_weekend=False,
            is_holiday=False,
            is_regular_open=False,
            ny_time=ny_dt,
            suggested_interval_seconds=RECONCILIATION_INTERVAL_STANDBY_SECONDS,
            description="장마감 후 배치: 당일 종가·SEC 공시 수집 및 AI 종목 분석 실행",
        )
    elif time(7, 0) <= ny_time < time(9, 30):
        # 프리마켓 및 승인 요청 시간 (07:00 ~ 09:30)
        return MarketPhaseInfo(
            phase=USMarketPhase.PRE_MARKET_APPROVAL,
            is_weekend=False,
            is_holiday=False,
            is_regular_open=False,
            ny_time=ny_dt,
            suggested_interval_seconds=120.0,
            description="프리마켓 시간대: 실시간 뉴스/센티먼트 반영 및 Discord 승인 요청 발송",
        )
    else:
        # 야간 대기 시간 (19:00 ~ 07:00)
        return MarketPhaseInfo(
            phase=USMarketPhase.STANDBY,
            is_weekend=False,
            is_holiday=False,
            is_regular_open=False,
            ny_time=ny_dt,
            suggested_interval_seconds=RECONCILIATION_INTERVAL_STANDBY_SECONDS,
            description="장외 심야 대기 모드: Heartbeat 유지 및 리소스 절약",
        )


__all__ = [
    "APPROVAL_POLL_SECONDS",
    "DEFAULT_ANALYSIS_INTERVAL_SECONDS",
    "HEARTBEAT_POLL_SECONDS",
    "EARLY_CLOSE",
    "MarketPhaseInfo",
    "NY_TZ",
    "RECONCILIATION_INTERVAL_OPEN_SECONDS",
    "RECONCILIATION_INTERVAL_STANDBY_SECONDS",
    "RISK_SNAPSHOT_INTERVAL_SECONDS",
    "SessionWindow",
    "USMarketPhase",
    "get_us_market_phase",
    "is_early_close_day",
    "is_us_market_holiday",
    "us_market_close_time",
]
