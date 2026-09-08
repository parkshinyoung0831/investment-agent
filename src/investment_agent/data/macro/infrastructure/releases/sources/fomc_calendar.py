"""Federal Reserve Board 공식 FOMC meeting calendar adapter.

FRED release 101은 FOMC와 관련된 모든 press release를 섞어 반환하므로 policy
decision event 일정의 source로 쓸 수 없다. 이 작은 parser는 Federal Reserve Board의
공식 calendar/historical pages에서 meeting 마지막 날만 읽는다. 다른 site를 fallback
으로 쓰지 않으며 markup contract가 바뀌면 fail-closed한다.
"""
from __future__ import annotations

import re
from datetime import date

import requests
from lxml import html

from investment_agent.platform.retry import retry_on_5xx

_CURRENT_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_HISTORICAL_URL = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
_CURRENT_FIRST_YEAR = 2021
_CURRENT_LAST_YEAR = 2027
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_HISTORICAL_HEADING = re.compile(
    r"(?P<months>[A-Za-z]+(?:/[A-Za-z]+)?)\s+(?P<days>\d+(?:\s*[-–]\s*\d+)?)\*?\s+Meeting\s*-\s*(?P<year>\d{4})",
    re.IGNORECASE,
)


class FomcCalendarError(ValueError):
    """official FOMC calendar markup/response가 release schedule 계약을 못 지킬 때."""


@retry_on_5xx()
def _fetch(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": "investment-agent-econ/2.0 (+official-calendar)"},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def fetch_dates(*, start: date, end: date) -> list[date]:
    """official pages에서 [start, end] FOMC policy-decision dates를 반환한다."""
    if start > end:
        raise FomcCalendarError("start must not exceed end")
    parsed: list[date] = []
    for year in range(start.year, min(end.year, _CURRENT_FIRST_YEAR - 1) + 1):
        rows = _historical_dates(_fetch(_HISTORICAL_URL.format(year=year)), expected_year=year)
        parsed.extend(rows)
    if start.year <= _CURRENT_LAST_YEAR and end.year >= _CURRENT_FIRST_YEAR:
        parsed.extend(_current_dates(_fetch(_CURRENT_URL)))
    return sorted({day for day in parsed if start <= day <= end})


def _historical_dates(document: str, *, expected_year: int) -> list[date]:
    tree = html.fromstring(document)
    output: list[date] = []
    for heading in tree.xpath("//h5"):
        text = " ".join(heading.itertext()).strip()
        matched = _HISTORICAL_HEADING.search(text)
        if matched is None or int(matched["year"]) != expected_year:
            continue
        output.append(_meeting_end_date(
            int(matched["year"]), matched["months"], matched["days"],
        ))
    if not output:
        raise FomcCalendarError(f"official historical calendar {expected_year} had no parsable meetings")
    return output


def _current_dates(document: str) -> list[date]:
    tree = html.fromstring(document)
    output: list[date] = []
    panels = tree.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' panel ')]")
    for panel in panels:
        heading = " ".join(panel.xpath(".//h4//text()"))
        matched = re.search(r"(\d{4})\s+FOMC\s+Meetings", heading, re.IGNORECASE)
        if matched is None:
            continue
        year = int(matched.group(1))
        for meeting in panel.xpath(
            ".//div[contains(concat(' ', normalize-space(@class), ' '), ' fomc-meeting ')]"
        ):
            # 미래 회의에는 아직 Statement 링크가 없다. 공식 calendar가
            # `fomc-meeting`으로 식별한 행 자체를 일정 계약으로 사용하고,
            # 부분 문자열로 하위 month/date div를 다시 잡지 않는다.
            months = " ".join(meeting.xpath(".//*[contains(@class, 'fomc-meeting__month')]//text()")).strip()
            days = " ".join(meeting.xpath(".//*[contains(@class, 'fomc-meeting__date')]//text()")).strip()
            if months and days:
                output.append(_meeting_end_date(year, months, days))
    if not output:
        raise FomcCalendarError("official current calendar had no parsable meetings")
    return output


def _meeting_end_date(year: int, months: str, days: str) -> date:
    month_tokens = re.findall(r"[A-Za-z]+", months)
    day_tokens = re.findall(r"\d{1,2}", days)
    if not month_tokens or not day_tokens:
        raise FomcCalendarError(f"unparseable FOMC meeting token: {months!r} {days!r}")
    month = _MONTHS.get(month_tokens[-1].lower())
    if month is None:
        raise FomcCalendarError(f"unrecognised FOMC month: {months!r}")
    return date(year, month, int(day_tokens[-1]))
