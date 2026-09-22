"""financial_versions 한 행에서 값을 읽는 순수 함수.

DB에 접근하지 않으므로 read model 계산과 카드 계산 양쪽에서 같이 쓴다. 계산의 owner는
reporting이고 알림 카드는 이것을 소비한다. `net_debt`·`cash_and_equivalents`도 여기가
유일한 정의다 — 예전에는 카드(`earnings_report.py`)와 화면(`services/earnings/metrics.py`)이
각자 구현해 한쪽만 단기투자자산을 반영했다(감사 RR2-08). EV 가산분(소수주주지분·우선주를
더하는 것) 자체는 `earnings_report.py`가 계속 소유한다.

`total_debt`는 `data/fundamentals/domain/services/leverage_metrics.py`에서 가져온다 — research도
같은 정의를 쓴다(`research/evidence/statistics.py`). 예전에는 두 계층이 각자 구현해 research가
운용리스 부채를 빠뜨렸다(감사 RR2-09).
"""
from __future__ import annotations

from investment_agent.data.fundamentals.domain.services.leverage_metrics import total_debt


def f(v) -> float | None:
    """숫자로 바꿀 수 없으면 None. Decimal·문자열·None이 섞여 들어온다."""
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def cash_and_equivalents(row: dict) -> float | None:
    """현금성 자산 = 현금·현금성자산 + 단기투자자산.

    둘 다 없으면 None이다. 합산 태그 하나만 보던 시절에는 분기 행의 98%에서 현금이
    0으로 취급돼 순부채가 계통적으로 과대평가됐다(감사 RR2-08) — 이 함수가 유일한 정의다.
    """
    cash = f(row.get("cash_and_cash_equivalents"))
    short_term = f(row.get("short_term_investments"))
    if cash is None and short_term is None:
        return None
    return (cash or 0.0) + (short_term or 0.0)


def net_debt(row: dict) -> float | None:
    """`total_debt` − `cash_and_equivalents`. 부채·현금 어느 쪽도 모르면 None이다."""
    debt = total_debt(row)
    if debt is None:
        return None
    return debt - (cash_and_equivalents(row) or 0.0)


__all__ = ["cash_and_equivalents", "f", "net_debt", "total_debt"]
