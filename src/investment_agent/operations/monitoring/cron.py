"""워크플로 cron이 특정 구간에 발화했어야 하는지 판정한다.

croniter를 쓰지 않는다 — 이 저장소의 cron은 전부 5필드(`분 시 일 월 요일`)에
`*`·정수·범위(`a-b`)·목록(`a,b`)·스텝(`*/n`)뿐이고, 판정 구간이 하루라 분 단위로
훑어도 1440회면 끝난다. 의존성을 늘리는 것보다 이쪽이 싸다.

GitHub Actions의 cron은 **항상 UTC**다. 요일은 일=0..토=6이라 파이썬의
weekday()(월=0..일=6)와 어긋나므로 변환해서 쓴다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


def _field(spec: str, low: int, high: int) -> set[int]:
    """cron 필드 하나를 허용 값 집합으로 편다."""
    allowed: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, raw_step = part.split("/", 1)
            step = int(raw_step)
        if part in ("*", ""):
            start, end = low, high
        elif "-" in part:
            first, last = part.split("-", 1)
            start, end = int(first), int(last)
        else:
            start = end = int(part)
        allowed.update(range(start, end + 1, step))
    return allowed


def parse(expr: str) -> list[set[int]]:
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"5필드 cron이 아니다: {expr!r}")
    return [_field(spec, low, high) for spec, (low, high) in zip(fields, _BOUNDS)]


def matches(expr: str, moment: datetime) -> bool:
    """moment(UTC)가 이 cron의 발화 시각인지."""
    minute, hour, dom, month, dow = parse(expr)
    # cron 요일은 일=0. 파이썬 weekday()는 월=0이라 한 칸 밀어 맞춘다.
    weekday = (moment.weekday() + 1) % 7
    if moment.minute not in minute or moment.hour not in hour or moment.month not in month:
        return False
    # 일자와 요일이 둘 다 제한돼 있으면 cron은 OR로 본다(표준 동작).
    dom_limited = dom != set(range(1, 32))
    dow_limited = dow != set(range(0, 7))
    if dom_limited and dow_limited:
        return moment.day in dom or weekday in dow
    return (moment.day in dom) and (weekday in dow)


def fires_between(expr: str, start: datetime, end: datetime) -> bool:
    """[start, end) 구간에 한 번이라도 발화 시각이 있었는지."""
    moment = start.replace(second=0, microsecond=0)
    while moment < end:
        if matches(expr, moment):
            return True
        moment += timedelta(minutes=1)
    return False
