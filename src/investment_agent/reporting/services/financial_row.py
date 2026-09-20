"""financial_versions 한 행에서 값을 읽는 순수 함수.

DB에 접근하지 않으므로 read model 계산과 카드 계산 양쪽에서 같이 쓴다. 계산의 owner는
reporting이고 알림 카드는 이것을 소비한다. EV 가산분 자체는 reporting/notifications/earnings_report.py가 소유한다 — 현금 정의가
카드의 표시 규칙과 함께 움직여서 여기 굳혀 두면 두 답이 갈린다.
"""
from __future__ import annotations


def f(v) -> float | None:
    """숫자로 바꿀 수 없으면 None. Decimal·문자열·None이 섞여 들어온다."""
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def total_debt(row: dict) -> float | None:
    """단기차입·유동성 장기부채·장기부채·운용리스 부채 합계. 구성요소가 하나도 없으면 모른다(None).

    결측을 0으로 접으면 부채 없는 회사처럼 보여 순부채·부채비율이 좋게 나온다.
    """
    total = f(row.get("total_debt_including_current"))
    if total is not None:
        return total
    parts = (
        f(row.get("short_term_debt")),
        f(row.get("current_portion_of_long_term_debt")),
        f(row.get("long_term_debt")),
        f(row.get("operating_lease_current_debt_equivalent")),
        f(row.get("operating_lease_non_current_debt_equivalent")),
    )
    known = [v for v in parts if v is not None]
    return sum(known) if known else None
