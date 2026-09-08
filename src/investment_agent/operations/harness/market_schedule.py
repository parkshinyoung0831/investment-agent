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


def is_us_market_holiday(d: date) -> bool:
    """미국 증권거래소(NYSE) 공식 휴장일 여부를 판정한다."""
    month = d.month
    day = d.day
    weekday = d.weekday()

    # 1. New Year's Day (1월 1일, 대체 공휴일 포함)
    if month == 1 and day == 1 and weekday < 5:
        return True
    if month == 1 and day == 2 and weekday == 0:
        return True
    if month == 12 and day == 31 and weekday == 4:
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
        if local.weekday() >= 5 or is_us_market_holiday(local.date()):
            return False
        return self.start <= local.time().replace(tzinfo=None) <= self.end

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
    if time(9, 30) <= ny_time < time(16, 0):
        # 본장 거래 시간 (09:30 ~ 16:00)
        return MarketPhaseInfo(
            phase=USMarketPhase.REGULAR_TRADING,
            is_weekend=False,
            is_holiday=False,
            is_regular_open=True,
            ny_time=ny_dt,
            suggested_interval_seconds=RECONCILIATION_INTERVAL_OPEN_SECONDS,
            description="미국 정규장 진행 중: 실시간 체결 감시 및 리스크 모니터링",
        )
    elif time(16, 0) <= ny_time < time(19, 0):
        # 장마감 직후 공시 및 분석 시간 (16:00 ~ 19:00)
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
    "MarketPhaseInfo",
    "NY_TZ",
    "RECONCILIATION_INTERVAL_OPEN_SECONDS",
    "RECONCILIATION_INTERVAL_STANDBY_SECONDS",
    "RISK_SNAPSHOT_INTERVAL_SECONDS",
    "SessionWindow",
    "USMarketPhase",
    "get_us_market_phase",
    "is_us_market_holiday",
]
