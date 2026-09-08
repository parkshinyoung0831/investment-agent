"""가격·재무 숫자를 LLM 대신 결정적으로 계산한다."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any


from investment_agent.platform.serialization import finite_float as _finite


def price_statistics(rows_desc: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """최신순 가격을 받아 수익률·변동성·낙폭을 계산한다."""
    rows = list(reversed(list(rows_desc)))
    closes = [_finite(row.get("close")) for row in rows]
    closes = [value for value in closes if value is not None and value > 0]
    if not closes:
        return {}
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    output: dict[str, Any] = {"latest_close": closes[-1], "observations": len(closes)}
    for horizon in (5, 20, 60, 120, 252):
        if len(closes) > horizon:
            output[f"return_{horizon}d"] = closes[-1] / closes[-horizon - 1] - 1
    if returns:
        mean = sum(returns[-20:]) / min(20, len(returns))
        variance = sum((value - mean) ** 2 for value in returns[-20:]) / max(1, min(20, len(returns)) - 1)
        output["volatility_20d_annualized"] = math.sqrt(variance) * math.sqrt(252)
    peak = closes[0]
    drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        drawdown = min(drawdown, close / peak - 1)
    output["max_drawdown_window"] = drawdown
    return output


def fundamental_statistics(rows_desc: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """공시 원시값에서 최신 수익성·성장·재무안전 지표를 계산한다."""
    rows = list(rows_desc)
    if not rows:
        return {}
    latest = rows[0]
    revenue = _finite(latest.get("revenue"))
    net_income = _finite(latest.get("net_income"))
    operating_income = _finite(latest.get("operating_income_loss"))
    cash = _finite(latest.get("cash_and_cash_equivalents"))
    debt = _finite(latest.get("total_debt_including_current"))
    output: dict[str, Any] = {
        "fiscal_year": latest.get("fiscal_year"),
        "fiscal_period": latest.get("fiscal_period"),
        "period_end": latest.get("period_end"),
        "filed_at": latest.get("filed_at"),
    }
    if revenue not in (None, 0):
        if net_income is not None:
            output["net_margin"] = net_income / revenue
        if operating_income is not None:
            output["operating_margin"] = operating_income / revenue
    if cash is not None and debt is not None:
        output["net_cash"] = cash - debt
    fiscal_year = _finite(latest.get("fiscal_year"))
    prior = next(
        (
            row for row in rows[1:]
            if fiscal_year is not None
            and _finite(row.get("fiscal_year")) == fiscal_year - 1
            and row.get("fiscal_period") == latest.get("fiscal_period")
            and _finite(row.get("revenue")) not in (None, 0)
        ),
        None,
    )
    if prior is not None and revenue is not None:
        prior_revenue = _finite(prior.get("revenue"))
        if prior_revenue not in (None, 0):
            output["revenue_growth_yoy"] = revenue / prior_revenue - 1
    return output


def estimate_statistics(rows_desc: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """컨센서스 최신값과 관측 스냅샷 변화만 계산한다."""
    rows = list(rows_desc)
    if not rows:
        return {}
    latest = rows[0]
    output = {
        key: latest.get(key)
        for key in (
            "target_fiscal_year", "target_fiscal_period", "target_period_end",
            "snapshot_date", "eps_avg", "eps_low", "eps_high", "eps_analysts",
            "revenue_avg", "revenue_low", "revenue_high", "revenue_analysts",
            "revisions_up_7d", "revisions_down_7d", "revisions_up_30d",
            "revisions_down_30d", "currency",
        )
    }
    comparable = next(
        (
            row for row in rows[1:]
            if row.get("target_fiscal_year") == latest.get("target_fiscal_year")
            and row.get("target_fiscal_period") == latest.get("target_fiscal_period")
        ),
        None,
    )
    if comparable is not None:
        for field in ("eps_avg", "revenue_avg"):
            current = _finite(latest.get(field))
            prior = _finite(comparable.get(field))
            if current is not None and prior not in (None, 0):
                output[f"{field}_change"] = current / prior - 1
    return output


def total_return(rows_asc: list[Mapping[str, Any]], end_index: int) -> float:
    """시작 종가 이후 배당을 포함한 단순 총수익률을 계산한다."""
    if not rows_asc or end_index >= len(rows_asc) or end_index < 1:
        raise ValueError("insufficient price path")
    start = _finite(rows_asc[0].get("close"))
    end = _finite(rows_asc[end_index].get("close"))
    if start is None or end is None or start <= 0:
        raise ValueError("invalid close in price path")
    dividends = sum(_finite(row.get("div_amount")) or 0.0 for row in rows_asc[1:end_index + 1])
    return (end + dividends) / start - 1

