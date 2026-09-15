"""System Portfolio의 비중 기반 회계. 가상 현금·수량·주문·체결이 없다.

한 거래일을 넘기는 계산은 둘뿐이다.

1. **평가**: 전날 비중 × (종가 변화 + 배당, 분할 보정) → 오늘 NAV와 drift된 비중.
2. **재조정**(목표가 있는 날만): drift된 비중 → 목표비중. 비용 = Σ|Δw| × (반스프레드 + 수수료)를 NAV에서 뺀다.

## 수익률은 저장한 전날 종가로 잰다

가격 이력은 분할 뒤 새 기준으로 다시 수집된다. 오늘 이력에서 전날 종가를 다시 읽으면 분할이 이미 반영된
값이라 분할일 수익률이 두 번 보정된다. 그래서 평가에 쓴 종가를 NAV 행에 함께 남기고, 다음 날은 그 값을
기준으로 `(오늘 종가 + 배당) × 분할비율 ÷ 전날 종가`를 쓴다. 한 기간 안에 분할과 배당이 함께 있으면
배당을 분할 뒤 1주 기준으로 본다.

## 목표는 판단 다음 정규장의 종가에 적용한다

판단 시각의 종가로 비중을 바꾸면 판단할 때 아직 몰랐던 가격 변화를 System이 가져간다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Mapping, Sequence

from investment_agent.data.market.domain.calendar import MARKET_TIMEZONE, REGULAR_OPEN
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL, validated_weights

INITIAL_NAV = 100.0


@dataclass(frozen=True)
class DailyMark:
    """거래일 하나를 마친 System 상태. 비중은 그날 재조정까지 반영한 값이다."""

    trade_date: str
    nav: float
    daily_return: float
    weights: dict[str, float]
    closes: dict[str, float]
    benchmark_nav: float
    benchmark_close: float
    turnover: float = 0.0
    cost: float = 0.0
    applied_target_id: str | None = None
    stale_price_tickers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def held_tickers(self) -> tuple[str, ...]:
        return tuple(sorted(symbol for symbol, weight in self.weights.items() if symbol != CASH_SYMBOL and weight > 0))


@dataclass(frozen=True)
class SessionPrice:
    """한 종목의 그날 종가와, 전날 평가 뒤 그날까지 생긴 배당·분할."""

    close: float | None
    dividend: float = 0.0
    split_ratio: float = 1.0


def first_session_after(decided_at: datetime, trade_dates: Sequence[str]) -> str | None:
    """판단 시각 뒤에 처음 열리는 정규장의 거래일. 아직 없으면 None."""
    local = decided_at.astimezone(MARKET_TIMEZONE)
    for trade_date in sorted(trade_dates):
        day = date.fromisoformat(str(trade_date)[:10])
        if datetime.combine(day, REGULAR_OPEN, tzinfo=MARKET_TIMEZONE) > local:
            return day.isoformat()
    return None


def session_price(rows: Sequence[Mapping], *, after: str | None, on: str) -> SessionPrice:
    """`after` 다음 날부터 `on`까지의 배당·분할과 `on`의 종가. 행은 `market_prices` 계약이다."""
    close: float | None = None
    dividend = 0.0
    split = 1.0
    for row in rows:
        trade_date = str(row["trade_date"])[:10]
        if trade_date > on or (after is not None and trade_date <= after):
            continue
        if row.get("div_amount"):
            dividend += float(row["div_amount"])
        if row.get("split_ratio"):
            split *= float(row["split_ratio"])
        if trade_date == on and row.get("close"):
            close = float(row["close"])
    return SessionPrice(close, dividend, split)


def _gross(previous_close: float, price: SessionPrice) -> float:
    if price.close is None:
        return 1.0
    return (price.close + price.dividend) * price.split_ratio / previous_close


def advance(
    previous: DailyMark | None,
    *,
    trade_date: str,
    prices: Mapping[str, SessionPrice],
    benchmark: SessionPrice,
    target: Mapping[str, float] | None = None,
    target_id: str | None = None,
    cost_rates: Mapping[str, float] | None = None,
) -> DailyMark:
    """전날 상태에서 하루를 넘긴다. 첫날은 목표가 있어야 시작한다(그 전 System은 전액 현금이다)."""
    if previous is None and target is None:
        raise ContractError("the first system session needs a target")
    if previous is not None and trade_date <= previous.trade_date:
        raise ContractError("system sessions must move forward")
    if benchmark.close is None:
        raise ContractError(f"benchmark close is missing on {trade_date}")
    if previous is None:
        nav, weights, closes, stale = INITIAL_NAV, {CASH_SYMBOL: 1.0}, {}, []
        benchmark_nav = INITIAL_NAV
    else:
        stale = []
        grown: dict[str, float] = {}
        closes = {}
        for symbol, weight in previous.weights.items():
            if symbol == CASH_SYMBOL or weight <= 0:
                continue
            price = prices.get(symbol, SessionPrice(None))
            if price.close is None:
                stale.append(symbol)
                closes[symbol] = previous.closes[symbol]
            else:
                closes[symbol] = price.close
            grown[symbol] = weight * _gross(previous.closes[symbol], price)
        grown[CASH_SYMBOL] = float(previous.weights.get(CASH_SYMBOL, 0.0))
        growth = math.fsum(grown.values())
        if not math.isfinite(growth) or growth <= 0:
            raise ContractError(f"system portfolio growth is invalid on {trade_date}")
        nav = previous.nav * growth
        weights = {symbol: value / growth for symbol, value in grown.items()}
        benchmark_nav = previous.benchmark_nav * _gross(previous.benchmark_close, benchmark)
    turnover = cost = 0.0
    if target is not None:
        goal = validated_weights(target)
        missing = sorted(symbol for symbol, weight in goal.items()
                         if symbol != CASH_SYMBOL and weight > 0 and prices.get(symbol, SessionPrice(None)).close is None)
        if missing:
            raise ContractError("target symbols have no close on the apply session: " + ", ".join(missing))
        rates = dict(cost_rates or {})
        symbols = set(goal) | set(weights)
        turnover = 0.5 * math.fsum(abs(goal.get(symbol, 0.0) - weights.get(symbol, 0.0)) for symbol in symbols)
        traded = {symbol: abs(goal.get(symbol, 0.0) - weights.get(symbol, 0.0))
                  for symbol in symbols if symbol != CASH_SYMBOL}
        unpriced = sorted(symbol for symbol, amount in traded.items() if amount > 1e-12 and symbol not in rates)
        if unpriced:
            raise ContractError("trading cost rates are missing: " + ", ".join(unpriced))
        cost = math.fsum(amount * float(rates.get(symbol, 0.0)) for symbol, amount in traded.items())
        nav *= 1.0 - cost
        weights = {symbol: weight for symbol, weight in goal.items() if weight > 0 or symbol == CASH_SYMBOL}
        closes = {symbol: (prices[symbol].close if prices.get(symbol) and prices[symbol].close is not None
                           else closes[symbol])
                  for symbol in weights if symbol != CASH_SYMBOL}
        stale = [symbol for symbol in stale if symbol in weights]
    daily_return = nav / previous.nav - 1.0 if previous is not None else nav / INITIAL_NAV - 1.0
    return DailyMark(
        trade_date=trade_date, nav=nav, daily_return=daily_return, weights=weights, closes=closes,
        benchmark_nav=benchmark_nav, benchmark_close=float(benchmark.close), turnover=turnover, cost=cost,
        applied_target_id=target_id if target is not None else None, stale_price_tickers=tuple(sorted(stale)),
    )


def performance_summary(history: Sequence[DailyMark | Mapping], *, periods: Mapping[str, int] | None = None) -> dict:
    """누적·기간 수익률, SPY 대비, 최대 낙폭, 연 변동성, 연 회전율·비용. 화면·카드의 공통 요약이다."""
    rows = [row if isinstance(row, Mapping) else row.__dict__ for row in history]
    if not rows:
        return {"days": 0}
    navs = [float(row["nav"]) for row in rows]
    benchmarks = [float(row["benchmark_nav"]) for row in rows]
    peak, max_drawdown = INITIAL_NAV, 0.0
    for value in navs:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, 1.0 - value / peak)
    returns = [float(row["daily_return"]) for row in rows[1:]]
    volatility = None
    if len(returns) >= 2:
        mean = math.fsum(returns) / len(returns)
        variance = math.fsum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
        volatility = math.sqrt(variance) * math.sqrt(252)
    years = max(len(rows) / 252.0, 1 / 252.0)
    summary = {
        "days": len(rows),
        "start_date": rows[0]["trade_date"],
        "end_date": rows[-1]["trade_date"],
        "nav": navs[-1],
        "total_return": navs[-1] / INITIAL_NAV - 1.0,
        "benchmark_return": benchmarks[-1] / INITIAL_NAV - 1.0,
        "excess_return": navs[-1] / INITIAL_NAV - benchmarks[-1] / INITIAL_NAV,
        "max_drawdown": max_drawdown,
        "annualized_volatility": volatility,
        "annualized_turnover": math.fsum(float(row["turnover"]) for row in rows) / years,
        "total_cost": math.fsum(float(row["cost"]) for row in rows),
        "cash_weight": float(dict(rows[-1]["weights"]).get(CASH_SYMBOL, 0.0)),
    }
    for name, days in (periods or {"1M": 21, "3M": 63, "6M": 126, "1Y": 252}).items():
        if len(rows) > days:
            base, base_benchmark = navs[-days - 1], benchmarks[-days - 1]
            summary[f"return_{name}"] = navs[-1] / base - 1.0
            summary[f"excess_return_{name}"] = navs[-1] / base - benchmarks[-1] / base_benchmark
    return summary


__all__ = [
    "DailyMark",
    "INITIAL_NAV",
    "SessionPrice",
    "advance",
    "first_session_after",
    "performance_summary",
    "session_price",
]
