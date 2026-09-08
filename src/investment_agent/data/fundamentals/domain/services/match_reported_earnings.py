"""8-K 접수일과 Yahoo 발표 실적 이력을 안전하게 연결한다."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date

REPORT_DATE_TOLERANCE_DAYS = 3


def match_reported_earnings(
    reported_earnings: Mapping[str, Mapping[str, float | None]],
    filed_at: str,
) -> tuple[str, Mapping[str, float | None]] | None:
    """같은 실적 발표의 Yahoo 행을 날짜 오차 범위에서 하나만 고른다.

    장 마감 뒤 SEC 접수가 다음 영업일로 밀릴 수 있으므로 날짜가 완전히 같을 것을
    요구하지 않는다. 반대로 다른 분기 행이 섞이지 않도록 허용 범위는 좁게 둔다.
    """
    try:
        filing_day = date.fromisoformat(filed_at)
    except (TypeError, ValueError):
        return None

    candidates: list[tuple[int, bool, str, Mapping[str, float | None]]] = []
    for report_date, values in reported_earnings.items():
        try:
            report_day = date.fromisoformat(report_date)
        except (TypeError, ValueError):
            continue
        distance = abs((report_day - filing_day).days)
        if distance <= REPORT_DATE_TOLERANCE_DAYS:
            candidates.append((distance, report_day > filing_day, report_date, values))
    if not candidates:
        return None
    _, _, report_date, values = min(candidates, key=lambda candidate: candidate[:2])
    return report_date, values


__all__ = ["REPORT_DATE_TOLERANCE_DAYS", "match_reported_earnings"]
