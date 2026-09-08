"""매크로 관측값의 기준일과 지연 상태를 일관되게 계산한다."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

# 달력 기준 허용 지연일. 주말과 공휴일을 감안해 일간은 금요일 관측값이
# 월요일 아침까지는 정상으로 보이도록 3일을 허용한다.
MAX_AGE_DAYS = {
    "daily": 3,
    "weekly": 10,
    "monthly": 45,
    "quarterly": 135,
}


def kst_today() -> date:
    """실행 위치와 관계없이 한국 시간의 오늘을 반환한다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def freshness_for(
    obs_date: date | str | None,
    frequency: str,
    *,
    as_of: date | None = None,
) -> dict[str, int | str | None]:
    """관측 기준일의 나이와 UI/알림용 freshness 상태를 반환한다.

    일간 시세와 감시 지표의 지연 상태에 사용한다.
    """
    if not obs_date:
        return {"obs_date": None, "age_days": None, "state": "missing"}

    parsed = obs_date if isinstance(obs_date, date) else date.fromisoformat(str(obs_date))
    age_days = max(0, ((as_of or kst_today()) - parsed).days)
    max_age = MAX_AGE_DAYS.get(frequency, MAX_AGE_DAYS["daily"])
    state = "fresh" if age_days <= max_age else "stale"
    return {"obs_date": parsed.isoformat(), "age_days": age_days, "state": state}
