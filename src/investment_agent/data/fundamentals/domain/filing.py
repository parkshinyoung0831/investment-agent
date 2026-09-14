"""공시와 회계기간을 식별하는 순수 값 객체."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SUPPORTED_FORMS: tuple[str, ...] = ("10-K", "10-Q", "10-K/A", "10-Q/A")
SUPPORTED_STATEMENTS: tuple[str, ...] = ("BS", "IS", "CF")

_SEC_TIMEZONE = ZoneInfo("America/New_York")


def normalize_form(form_type: str) -> str:
    """수정 공시 표기를 원 공시 유형으로 정규화한다."""
    return (form_type or "").replace("/A", "").strip()


def filing_available_at(filing_date: date | str) -> datetime:
    """일자 정밀도 SEC 제출일을 **다음 날 0시(뉴욕)**부터 알 수 있던 것으로 본다.

    `filing_date`는 시각이 없는 ET 날짜다. EDGAR는 늦게 접수된 공시(10-K·10-Q·8-K는
    17:30, 일부 양식은 22:00 이후)를 다음 영업일 날짜로 붙이므로, 날짜가 D인 공시는
    D 자정(ET) 전에 공개가 끝나 있다. 그날 0시로 잡으면 장 마감 뒤 발표된 실적을 그날
    아침에 이미 안 것으로 만들고, UTC 0시로 잡으면 뉴욕 전날 저녁이 된다.
    """
    day = filing_date if isinstance(filing_date, date) else date.fromisoformat(str(filing_date)[:10])
    return datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=_SEC_TIMEZONE)
