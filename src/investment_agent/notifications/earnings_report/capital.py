"""자본구조에서 EV 가산분을 계산하는 순수 함수.

financial_versions 한 행을 받아 총부채·현금성자산·우선주·비지배지분을 조합한다. DB에 접근하지
않으므로 조회 결과와 시점정합 스냅샷(candidates.py) 양쪽에서 같이 쓴다.
"""
from __future__ import annotations

# total_debt_including_current 컬럼이 없는 DB에서 쓰는 축소 목록(구성 부채를 직접 합산).


def f(v) -> float | None:
    """숫자로 바꿀 수 없으면 None. Decimal·문자열·None이 섞여 들어온다."""
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def total_debt(row: dict) -> float:
    """단기차입·유동성 장기부채·장기부채·운용리스 부채 합계."""
    total = f(row.get("total_debt_including_current"))
    if total is not None:
        return total
    return sum(
        v or 0.0
        for v in (
            f(row.get("short_term_debt")),
            f(row.get("current_portion_of_long_term_debt")),
            f(row.get("long_term_debt")),
            f(row.get("operating_lease_current_debt_equivalent")),
            f(row.get("operating_lease_non_current_debt_equivalent")),
        )
    )


def adjustment(row: dict) -> float:
    """EV 가산분 = 총부채 - 현금성자산 + 우선주 + 비지배지분."""
    debt = total_debt(row)
    cash_parts = [f(row.get("cash_and_cash_equivalents")), f(row.get("short_term_investments"))]
    present = [v for v in cash_parts if v is not None]
    cash = sum(present) if present else None
    return (
        debt
        - (cash or 0.0)
        + (f(row.get("preferred_stock")) or 0.0)
        + (f(row.get("minority_interest_balance")) or 0.0)
    )
