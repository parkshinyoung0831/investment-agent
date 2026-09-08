"""실적 카드와 실적 화면이 함께 쓰는 파생 지표 계산 (SSOT).

financials 원값에서 마진·FCF·순부채·YoY를 직접 계산한다. 부호 규약은
fundamentals.v_quality / v_value 뷰와 맞춘다:
  FCF     = 영업현금흐름 − capex(양수 = 유출)
  순부채  = 단기차입 + 장기차입 + 운용리스(유동/비유동) − 현금성·시장성 자산
YoY는 전년 동기(prev) 행과 비교한다.
"""
from __future__ import annotations

from typing import Any


def as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _yoy(curr: float | None, prev: float | None) -> float | None:
    if curr is None or prev is None or prev == 0:
        return None
    return (curr - prev) / abs(prev)


def _margin(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _total_debt(row: dict) -> float | None:
    total = as_float(row.get("total_debt_including_current"))
    if total is not None:
        return total
    parts = [
        as_float(row.get("short_term_debt")),
        as_float(row.get("current_portion_of_long_term_debt")),
        as_float(row.get("long_term_debt")),
        as_float(row.get("operating_lease_current_debt_equivalent")),
        as_float(row.get("operating_lease_non_current_debt_equivalent")),
    ]
    vals = [p for p in parts if p is not None]
    return sum(vals) if vals else None


def _cash(row: dict) -> float | None:
    """현금성 자산 = 현금·현금성자산 + 단기투자자산.

    둘 다 없으면 None이다. 합산 태그 하나만 보던 시절에는 분기 행의 98%에서
    현금이 0으로 취급돼 순부채가 계통적으로 과대평가됐다.
    """
    cash = as_float(row.get("cash_and_cash_equivalents"))
    short_term = as_float(row.get("short_term_investments"))
    if cash is None and short_term is None:
        return None
    return (cash or 0.0) + (short_term or 0.0)


def _net_debt(row: dict) -> float | None:
    debt = _total_debt(row)
    if debt is None:
        return None
    return debt - (_cash(row) or 0.0)


def _fcf(row: dict) -> float | None:
    ocf = as_float(row.get("net_cash_from_operating_activities"))
    if ocf is None:
        return None
    return ocf - (as_float(row.get("capital_expenses")) or 0.0)


def _eps_diluted(row: dict) -> float | None:
    """분기 희석 EPS = 보통주 귀속 순이익 / 희석 평균주식수.
    원천 EPS 컬럼을 보관하지 않으므로 순이익·희석주식수로 직접 계산한다."""
    ni = as_float(row.get("net_income_to_common_shareholders"))
    if ni is None:
        ni = as_float(row.get("net_income"))
    sh = as_float(row.get("shares_fully_diluted_average"))
    if ni is None or not sh:
        return None
    return ni / sh


def derive(row: dict, prev: dict | None) -> dict:
    """헤드라인 행 + 전년 동기 행 → 카드·등급 판정에 쓸 스칼라 dict."""
    rev = as_float(row.get("revenue"))
    op = as_float(row.get("operating_income_loss"))
    ni = as_float(row.get("net_income"))
    gross = as_float(row.get("gross_profit"))
    eps = _eps_diluted(row)

    p_rev = as_float(prev.get("revenue")) if prev else None
    p_op = as_float(prev.get("operating_income_loss")) if prev else None
    p_ni = as_float(prev.get("net_income")) if prev else None
    p_eps = _eps_diluted(prev) if prev else None
    p_gross_margin = _margin(as_float(prev.get("gross_profit")), p_rev) if prev else None
    p_op_margin = _margin(as_float(prev.get("operating_income_loss")), p_rev) if prev else None
    p_net_margin = _margin(p_ni, p_rev) if prev else None

    gross_margin = _margin(gross, rev)
    op_margin = _margin(op, rev)
    net_margin = _margin(ni, rev)

    return {
        "revenue": rev,
        "operating_income": op,
        "net_income": ni,
        "eps_diluted": eps,
        "gross_margin": gross_margin,
        "operating_margin": op_margin,
        "net_margin": net_margin,
        "fcf": _fcf(row),
        "cash": _cash(row),
        "net_debt": _net_debt(row),
        "buyback": as_float(row.get("stock_repurchase_payments")),
        "dividends": as_float(row.get("common_dividends_paid")),
        "revenue_yoy": _yoy(rev, p_rev),
        "operating_income_yoy": _yoy(op, p_op),
        "net_income_yoy": _yoy(ni, p_ni),
        "eps_yoy": _yoy(eps, p_eps),
        "gross_margin_delta_yoy": (
            gross_margin - p_gross_margin
            if gross_margin is not None and p_gross_margin is not None
            else None
        ),
        "operating_margin_delta_yoy": (
            op_margin - p_op_margin
            if op_margin is not None and p_op_margin is not None
            else None
        ),
        "net_margin_delta_yoy": (
            net_margin - p_net_margin
            if net_margin is not None and p_net_margin is not None
            else None
        ),
        "net_income_now": ni,
        "net_income_prev": p_ni,
        "is_first": prev is None,
    }


__all__ = ["as_float", "derive"]
