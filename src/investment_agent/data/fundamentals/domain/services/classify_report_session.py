"""발표 예정 시각을 거래 세션 구간(BMO/AMC)으로 분류한다.

발표 '날짜'만으로는 언제 수집을 걸어야 하는지 알 수 없다. 같은 날짜라도 장전
발표는 06:00~09:30 ET, 장후 발표는 16:00~17:30 ET에 8-K가 접수되므로 수집을 거는
시각이 8시간 이상 벌어진다. 날짜만 보고 하루 한 번 훑으면 장전 발표는 최대
15시간 늦게 잡힌다.
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# 세션 구간. 미국 정규장은 09:30~16:00 ET다.
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

BMO = "bmo"
AMC = "amc"
DMH = "dmh"
UNKNOWN = "unknown"

SESSIONS: frozenset[str] = frozenset({BMO, AMC, DMH, UNKNOWN})

# 세션별로 8-K가 실제로 접수되는 창(ET). 수집 job이 언제 깨어 있어야 하는지를
# 정한다. 상한은 관측된 지연을 감안해 넉넉히 잡는다 — 좁게 잡아 놓치는 쪽이
# 넓게 잡아 몇 번 더 훑는 쪽보다 나쁘다.
COLLECT_WINDOW_ET: dict[str, tuple[time, time]] = {
    BMO: (time(6, 0), time(10, 30)),
    AMC: (time(16, 0), time(20, 0)),
    # 장중 발표는 S&P 500 규모에서 사실상 없다. dmh로 분류된 값은 대개 야후의
    # 시각 미정 placeholder(15:00)이므로 좁은 장중 창에 가두면 실제 발표를 놓친다.
    DMH: (time(6, 0), time(20, 0)),
    UNKNOWN: (time(6, 0), time(20, 0)),
}

# 야후는 시각이 아직 공지되지 않은 '미래' 발표에 15:00 ET를 넣는다. 실측:
# AMAT는 과거 24회가 16:00인데 다음 예정만 15:00, BRK-B는 과거 24회가 08:00인데
# 다음 예정만 15:00이었다. 그대로 믿으면 수집 창이 통째로 어긋난다.
PLACEHOLDER_ET = time(15, 0)


def classify_session(moment: datetime | None) -> str:
    """ET 기준 발표 시각을 세션으로 분류한다.

    tz 정보가 없는 값은 ET로 간주한다 — yfinance의 earnings_dates 인덱스는
    America/New_York로 오지만, 저장 후 다시 읽을 때 naive가 되는 경로가 있다.
    """
    if moment is None:
        return UNKNOWN
    et = moment.astimezone(ET) if moment.tzinfo else moment.replace(tzinfo=ET)
    clock = et.timetz().replace(tzinfo=None)
    if clock < MARKET_OPEN:
        return BMO
    if clock >= MARKET_CLOSE:
        return AMC
    return DMH


def is_placeholder_time(moment: datetime | None) -> bool:
    """야후가 '시각 미정'에 쓰는 자리표시 시각인지."""
    if moment is None:
        return False
    et = moment.astimezone(ET) if moment.tzinfo else moment.replace(tzinfo=ET)
    return et.timetz().replace(tzinfo=None) == PLACEHOLDER_ET


def session_from_history(moments: list[datetime]) -> str:
    """과거 발표 시각들의 최빈 세션. 예정 시각이 자리표시일 때 대신 쓴다.

    회사는 장전·장후 습관을 좀처럼 바꾸지 않는다. 넓은 창으로 하루 종일 훑는
    것보다 과거 패턴을 따르는 쪽이 정확하고 SEC 호출도 적다.
    """
    counts: dict[str, int] = {}
    for moment in moments:
        session = classify_session(moment)
        if session in (BMO, AMC):
            counts[session] = counts.get(session, 0) + 1
    if not counts:
        return UNKNOWN
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def resolve_session(upcoming: datetime | None, history: list[datetime] | None = None) -> str:
    """예정 시각과 과거 이력을 함께 보고 세션을 정한다."""
    session = classify_session(upcoming)
    if session in (BMO, AMC):
        return session
    # dmh거나 자리표시면 그 회사의 과거 습관을 따른다.
    from_history = session_from_history(history or [])
    return from_history if from_history != UNKNOWN else session


def collect_window(session: str) -> tuple[time, time]:
    """해당 세션에서 8-K를 훑어야 하는 ET 시각 구간."""
    return COLLECT_WINDOW_ET.get(session, COLLECT_WINDOW_ET[UNKNOWN])


def is_within_collect_window(session: str, moment: datetime) -> bool:
    """지금이 그 세션의 수집 창 안인지 판정한다."""
    et = moment.astimezone(ET) if moment.tzinfo else moment.replace(tzinfo=ET)
    start, end = collect_window(session)
    clock = et.timetz().replace(tzinfo=None)
    return start <= clock <= end
