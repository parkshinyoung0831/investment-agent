"""세그먼트 fact가 공시의 현재 보고기간에 속하는지 판정한다."""
from __future__ import annotations

from datetime import date

_FLOW_END_TOLERANCE_DAYS = 31


def belongs_to_report_period(
    period_end: date,
    report_end: date,
    *,
    is_instant: bool,
) -> bool:
    """기간말 잔액은 정확한 기준일만, 유량은 월말 차이까지 허용한다."""
    if is_instant:
        return period_end == report_end
    return abs((period_end - report_end).days) <= _FLOW_END_TOLERANCE_DAYS
