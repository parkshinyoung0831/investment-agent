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
    if len(returns) >= 120:
        window = returns[-252:]
        mean = sum(window) / len(window)
        output["volatility_252d_annualized"] = math.sqrt(
            sum((value - mean) ** 2 for value in window) / (len(window) - 1)
        ) * math.sqrt(252)
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
    if prior is not None and net_income is not None:
        prior_income = _finite(prior.get("net_income"))
        if prior_income not in (None, 0):
            # 적자에서 흑자로 바뀌면 부호가 뒤집히므로 전년 값의 절대값으로 나눈다.
            output["net_income_growth_yoy"] = (net_income - prior_income) / abs(prior_income)
    output.update(quality_statistics(rows))
    return output


_TTM_QUARTERS = 4
# 이익률의 흔들림을 잴 분기 수. 2년이면 한 번의 계절 주기를 두 번 본다.
_STABILITY_QUARTERS = 8


def _quarters_desc(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """분기별 한 행씩 최신 회계기간순. 같은 분기 정정본은 읽기 경계가 이미 하나로 골랐다."""
    seen: set[tuple[Any, Any]] = set()
    ordered: list[Mapping[str, Any]] = []
    for row in sorted(rows, key=lambda item: str(item.get("period_end") or ""), reverse=True):
        key = (row.get("fiscal_year"), row.get("fiscal_period"))
        if not row.get("period_end") or key in seen:
            continue
        seen.add(key)
        ordered.append(row)
    return ordered


def _sum(rows: list[Mapping[str, Any]], field: str) -> float | None:
    values = [_finite(row.get(field)) for row in rows]
    if len(values) < _TTM_QUARTERS or any(value is None for value in values):
        return None
    return math.fsum(values)  # type: ignore[arg-type]


def _gross_profit(row: Mapping[str, Any]) -> float | None:
    """매출총이익을 따로 보고하지 않는 회사가 많아 매출 - 매출원가로 채운다."""
    gross = _finite(row.get("gross_profit"))
    if gross is not None:
        return gross
    revenue = _finite(row.get("revenue"))
    cost = _finite(row.get("cost_of_goods_and_services_sold"))
    return revenue - cost if revenue is not None and cost is not None else None


def _total_debt(row: Mapping[str, Any]) -> float | None:
    """총차입 합계가 없으면 단기·유동성장기·장기 차입을 더한다. 어느 것도 없으면 모른다."""
    total = _finite(row.get("total_debt_including_current"))
    if total is not None:
        return total
    parts = [_finite(row.get(name)) for name in ("short_term_debt", "current_portion_of_long_term_debt", "long_term_debt")]
    known = [part for part in parts if part is not None]
    return math.fsum(known) if known else None


def _ratio(numerator: float | None, denominator: float | None, *, positive: bool = False) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    if positive and denominator < 0:
        return None
    return numerator / denominator


def quality_statistics(rows: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    """최근 4분기 합산(TTM)으로 수익성·현금 창출·재무건전성·이익 안정성을 계산한다.

    분기 하나라도 값이 없으면 그 지표는 만들지 않는다 — 3분기로 계산한 연간 값은 조용히 작다.
    자본잠식(자본 ≤ 0)이면 ROE는 의미가 없어 비운다. 값이 없다는 사실이 곧 정보다.
    """
    quarters = _quarters_desc(list(rows))
    ttm = quarters[:_TTM_QUARTERS]
    output: dict[str, float] = {}
    if len(ttm) < _TTM_QUARTERS:
        return output
    latest = ttm[0]
    revenue = _sum(ttm, "revenue")
    net_income = _sum(ttm, "net_income")
    operating = _sum(ttm, "operating_income_loss")
    gross_values = [_gross_profit(row) for row in ttm]
    gross = None if any(value is None for value in gross_values) else math.fsum(gross_values)  # type: ignore[arg-type]
    cash_flow = _sum(ttm, "net_cash_from_operating_activities")
    capex = _sum(ttm, "capital_expenses")
    interest = _sum(ttm, "interest_expense")
    equity = _finite(latest.get("common_equity"))
    assets = _finite(latest.get("assets"))
    debt = _total_debt(latest)
    values = {
        "roe_ttm": _ratio(net_income, equity, positive=True),
        "roa_ttm": _ratio(net_income, assets, positive=True),
        "gross_margin_ttm": _ratio(gross, revenue, positive=True),
        "operating_margin_ttm": _ratio(operating, revenue, positive=True),
        # capital_expenses는 유출을 양수로 적재한다(valuation 입력과 같은 규칙).
        "fcf_margin_ttm": _ratio(
            cash_flow - abs(capex) if cash_flow is not None and capex is not None else None, revenue, positive=True,
        ),
        # 이자비용이 없거나 음수(이자수익 순액)면 이자보상배율이 정의되지 않는다.
        "interest_coverage_ttm": _ratio(operating, interest) if interest is not None and interest > 0 else None,
        # 이익이 현금보다 크게 앞서는 정도. 높을수록 이익의 질이 낮다.
        "accruals_ttm": _ratio(
            net_income - cash_flow if net_income is not None and cash_flow is not None else None, assets, positive=True,
        ),
        "debt_to_equity": _ratio(debt, equity, positive=True),
    }
    prior = quarters[_TTM_QUARTERS:_TTM_QUARTERS * 2]
    prior_revenue = _sum(prior, "revenue") if len(prior) == _TTM_QUARTERS else None
    if revenue is not None and prior_revenue is not None and prior_revenue > 0:
        values["revenue_growth_ttm_yoy"] = revenue / prior_revenue - 1
    margins = [
        _ratio(_finite(row.get("operating_income_loss")), _finite(row.get("revenue")), positive=True)
        for row in quarters[:_STABILITY_QUARTERS]
    ]
    margins = [value for value in margins if value is not None]
    if len(margins) >= _TTM_QUARTERS:
        mean = math.fsum(margins) / len(margins)
        values["operating_margin_volatility"] = math.sqrt(
            math.fsum((value - mean) ** 2 for value in margins) / (len(margins) - 1)
        )
    for name, value in values.items():
        if value is not None and math.isfinite(value):
            output[name] = value
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
                # 적자 추정치에서도 방향이 맞도록 이전 값의 절대값으로 나눈다.
                output[f"{field}_change"] = (current - prior) / abs(prior)
    up = _finite(latest.get("revisions_up_30d"))
    down = _finite(latest.get("revisions_down_30d"))
    if up is not None and down is not None and up + down > 0:
        # 상향-하향 비율(-1~1). 개수 차이는 커버리지가 넓은 대형주에 치우친다.
        output["revision_breadth_30d"] = (up - down) / (up + down)
    return output


def total_return(rows_asc: list[Mapping[str, Any]], end_index: int) -> float:
    """시작 종가 이후 배당을 포함한 단순 총수익률을 계산한다."""
    if not rows_asc or end_index >= len(rows_asc) or end_index < 1:
        raise ValueError("insufficient price path")
    start = _finite(rows_asc[0].get("close"))
    end = _finite(rows_asc[end_index].get("close"))
    if start is None or end is None or start <= 0:
        raise ValueError("invalid close in price path")
    shares = 1.0
    dividends = 0.0
    for row in rows_asc[1:end_index + 1]:
        ratio = _finite(row.get("split_ratio"))
        if ratio is not None:
            if ratio <= 0:
                raise ValueError("invalid split ratio in price path")
            shares *= ratio
        dividends += shares * (_finite(row.get("div_amount")) or 0.0)
    return (end * shares + dividends) / start - 1

