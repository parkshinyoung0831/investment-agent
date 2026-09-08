"""FRED 발표 일정(release/dates) 어댑터.

macro/clients/fred.py는 관측치(series/observations)를 받아오고, 여기는 '언제 나오나'만
받아온다. 같은 FRED_API_KEY를 쓰지만 엔드포인트도 반환 모양도 달라 파일을 나눈다.
"""
from __future__ import annotations

import os
from datetime import date

import requests

from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import retry_on_5xx
from investment_agent.data.macro.infrastructure.releases.sources.actuals import _fred_slot

log = get_logger(__name__)
_BASE = "https://api.stlouisfed.org/fred/release/dates"

# FRED는 realtime 창 안에서만 일정을 준다. 기본값이 '오늘~오늘'이라 그대로 부르면
# 미래 일정이 한 건도 안 돌아온다 — 끝을 열어야 예정일이 보인다.
_REALTIME_END = "9999-12-31"


@retry_on_5xx()
def fetch_release_dates(release_id: int, *, start: date, end: date) -> list[date]:
    """release_id 하나의 발표 예정일을 [start, end] 구간으로 잘라 반환한다.

    include_release_dates_with_no_data가 핵심이다 — 빼면 '이미 값이 붙은' 과거
    일정만 돌아와서 캘린더가 텅 빈다.
    """
    _fred_slot()
    response = requests.get(
        _BASE,
        params={
            "release_id": release_id,
            "api_key": os.environ["FRED_API_KEY"],
            "file_type": "json",
            "realtime_start": start.isoformat(),
            "realtime_end": _REALTIME_END,
            "include_release_dates_with_no_data": "true",
            "sort_order": "asc",
            "limit": 1000,
        },
        timeout=30,
    )
    response.raise_for_status()
    dates = []
    for item in response.json().get("release_dates", []):
        parsed = date.fromisoformat(item["date"])
        if start <= parsed <= end:
            dates.append(parsed)
    return dates


def fetch_batch(
    release_ids: list[int], *, start: date, end: date,
) -> tuple[dict[int, list[date]], list[dict]]:
    """릴리스 단위로 한 번씩만 호출한다.

    지표 14종이 릴리스 9개를 공유하므로(CPI·Core CPI가 release 10 하나) 지표마다
    부르면 같은 응답을 다섯 번 더 받는다. 하나가 실패해도 나머지 일정은 살린다.
    """
    schedules: dict[int, list[date]] = {}
    failures: list[dict] = []
    for release_id in sorted(set(release_ids)):
        try:
            schedules[release_id] = fetch_release_dates(release_id, start=start, end=end)
            log.info("  OK release=%d (%d dates)", release_id, len(schedules[release_id]))
        except Exception as exc:  # noqa: BLE001 - 릴리스별 실패를 모아 부분 성공을 보존한다.
            log.warning("  FAIL release=%d: %s", release_id, exc)
            failures.append({
                "release_id": release_id, "error": str(exc), "type": type(exc).__name__,
            })
    return schedules, failures
