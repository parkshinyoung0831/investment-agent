"""날짜 보조 함수 (기준일=decision·적용일=apply 계산)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd


def decision_and_apply_dates(prices: pd.DataFrame) -> tuple[date, date]:
    """기준일(decision)=가장 최근 끝난 달의 마지막 날, 적용일(apply)=그 다음 달 1일. KST 기준."""
    decision = prices.index[-1].date()
    apply_dt = (decision + timedelta(days=1)).replace(day=1)
    today_kst = datetime.now(ZoneInfo("Asia/Seoul")).date()
    if decision >= today_kst.replace(day=1):
        raise RuntimeError(f"decision_date {decision}가 현재 달 이상입니다")
    return decision, apply_dt
