"""실적 카드와 실적 화면이 함께 쓰는 파생 지표 계산 (SSOT).

financials 원값에서 마진·FCF·순부채·YoY를 직접 계산한다. 부호 규약은
fundamentals.v_quality / v_value 뷰와 맞춘다:
  FCF     = 영업현금흐름 − capex(양수 = 유출)
  순부채  = 단기차입 + 장기차입 + 운용리스(유동/비유동) − 현금성·시장성 자산
YoY는 전년 동기(prev) 행과 비교한다.
"""
from __future__ import annotations

from typing import Any

from investment_agent.reporting.services.financial_row import cash_and_equivalents, net_debt, total_debt


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


def _fcf(row: dict) -> float | None:
    ocf = as_float(row.get("net_cash_from_operating_activities"))
    if ocf is None:
        return None
    return ocf - (as_float(row.get("capital_expenses")) or 0.0)


def eps_diluted(row: dict) -> float | None:
    """분기 희석 EPS. 회사가 보고한 값(`eps_diluted_gaap`)만 쓴다.

    순이익 ÷ 희석주식수로 다시 계산하지 않는다. 그 두 입력은 주식수 스케일이 어긋나거나
    귀속 순이익이 다른 개념에 매핑된 행이 있어서, 재계산하면 MCD가 3,321,614.40, UNH가
    0.07처럼 예외 없이 틀린 값이 카드에 나간다. 보고 EPS가 없으면 빈칸이 틀린 숫자보다 낫다.
    """
    return as_float(row.get("eps_diluted_gaap"))


def derive(row: dict, prev: dict | None) -> dict:
    """헤드라인 행 + 전년 동기 행 → 카드·등급 판정에 쓸 스칼라 dict."""
    rev = as_float(row.get("revenue"))
    op = as_float(row.get("operating_income_loss"))
    ni = as_float(row.get("net_income"))
    gross = as_float(row.get("gross_profit"))
    eps = eps_diluted(row)

    p_rev = as_float(prev.get("revenue")) if prev else None
    p_op = as_float(prev.get("operating_income_loss")) if prev else None
    p_ni = as_float(prev.get("net_income")) if prev else None
    p_eps = eps_diluted(prev) if prev else None
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
        "cash": cash_and_equivalents(row),
        "net_debt": net_debt(row),
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
