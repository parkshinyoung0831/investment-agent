"""가상계좌의 주문 계획·체결·평가를 결정론적으로 계산하는 순수 계층.

## 체결 규칙은 optimizer의 비용 가정과 같다

optimizer는 거래 전에 `반스프레드 + impact·σ·√(주문액/ADV)`만큼 비용을 뺀다. 가상 체결이
그보다 싸면 Shadow 성과가 실제보다 좋게 나오고, 비싸면 좋은 정책을 버린다. 그래서 같은 식을
쓰고, 수수료는 백테스트와 같은 `TransactionCostModel`의 비율을 쓴다.

## 체결 시점

판단 시각 뒤에 **처음 열리는 정규장 시가**에 체결한다. 판단 당일 종가처럼 판단 시점에 아직
몰랐던 가격으로 체결하면 미래를 본 성과가 된다. 그 봉이 확정되기 전에는 체결하지 않는다.

## 현금보다 많이 사지 않는다

매도 체결 대금이 들어온 뒤 남은 현금 안에서만 매수한다. 모자라면 매수 주문을 같은 비율로
줄인다. 한 봉의 거래량 × 참여율 상한을 넘는 수량은 부분체결로 남기고 나머지는 취소한다 —
다음 판단이 현재 상태에서 다시 계산한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Mapping, Sequence

from investment_agent.data.market.domain.calendar import MARKET_TIMEZONE, REGULAR_OPEN
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL

_EPSILON = 1e-9


def _floor(value: float, decimals: int) -> float:
    scale = 10 ** decimals
    return math.floor(value * scale + 1e-12) / scale


@dataclass(frozen=True)
class SimulationPolicy:
    """가상 체결 가정. 실계좌 경로의 한도·비용 가정과 같은 값을 기본으로 둔다."""

    min_order_notional: float
    quantity_decimals: int
    max_participation: float
    impact_coefficient: float
    commission_rate: float
    buy_cash_buffer: float = 0.005

    def __post_init__(self) -> None:
        for name in ("min_order_notional", "impact_coefficient", "commission_rate", "buy_cash_buffer"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ContractError(f"{name} must be finite and non-negative")
        if not 0 < self.max_participation <= 1:
            raise ContractError("max_participation must be in (0, 1]")


@dataclass(frozen=True)
class BookState:
    cash: float
    positions: Mapping[str, float] = field(default_factory=dict)

    def nav(self, prices: Mapping[str, float]) -> float:
        missing = sorted(ticker for ticker in self.positions if ticker not in prices)
        if missing:
            raise ContractError(f"no price to value held positions: {missing}")
        return self.cash + math.fsum(quantity * prices[ticker] for ticker, quantity in self.positions.items())


@dataclass(frozen=True)
class PlannedOrder:
    ticker: str
    side: str
    quantity: float
    reason_code: str


@dataclass(frozen=True)
class FillBar:
    """체결 봉과, 그 봉 **이전** 이력으로만 추정한 비용 재료."""

    trade_date: str
    open: float
    volume: float
    half_spread: float
    daily_volatility: float
    adv_usd: float


@dataclass(frozen=True)
class SimulatedFill:
    ticker: str
    side: str
    quantity: float
    reference_price: float
    fill_price: float
    spread_cost: float
    impact_cost: float
    commission: float

    @property
    def notional(self) -> float:
        return self.quantity * self.fill_price


def fill_session_date(decided_at: datetime, trade_dates: Sequence[str]) -> str | None:
    """판단 시각 뒤에 처음 열리는 정규장의 거래일. 아직 없으면 None."""
    local = decided_at.astimezone(MARKET_TIMEZONE)
    for trade_date in sorted(trade_dates):
        day = date.fromisoformat(str(trade_date)[:10])
        opens_at = datetime.combine(day, REGULAR_OPEN, tzinfo=MARKET_TIMEZONE)
        if opens_at > local:
            return day.isoformat()
    return None


def plan_rebalance(
    state: BookState,
    *,
    prices: Mapping[str, float],
    target_weights: Mapping[str, float],
    policy: SimulationPolicy,
    reason_codes: Mapping[str, str] | None = None,
) -> list[PlannedOrder]:
    """목표 비중까지의 주문. 매도가 먼저 오고, 최소 주문액보다 작은 차이는 거래하지 않는다."""
    nav = state.nav(prices)
    if nav <= 0:
        raise ContractError("book NAV must be positive to rebalance")
    reasons = reason_codes or {}
    tickers = sorted((set(state.positions) | set(target_weights)) - {CASH_SYMBOL})
    orders: list[PlannedOrder] = []
    for ticker in tickers:
        price = prices.get(ticker)
        if price is None or price <= 0:
            raise ContractError(f"no price to plan an order for {ticker}")
        current = state.positions.get(ticker, 0.0)
        target_quantity = float(target_weights.get(ticker, 0.0)) * nav / price
        delta = target_quantity - current
        if abs(delta) * price < policy.min_order_notional:
            continue
        if delta < 0:
            # 전량 청산은 보유 수량 그대로 판다. 반올림으로 찌꺼기 수량이 남지 않게 한다.
            quantity = current if target_weights.get(ticker, 0.0) <= 0 else _floor(-delta, policy.quantity_decimals)
            side = "sell"
        else:
            quantity = _floor(delta, policy.quantity_decimals)
            side = "buy"
        if quantity <= 0:
            continue
        orders.append(PlannedOrder(ticker, side, quantity, reasons.get(ticker, "REBALANCE")))
    return sorted(orders, key=lambda order: (order.side != "sell", order.ticker))


def _execution_price(side: str, bar: FillBar, notional: float, policy: SimulationPolicy) -> tuple[float, float, float]:
    impact_rate = policy.impact_coefficient * bar.daily_volatility * math.sqrt(max(notional, 0.0) / bar.adv_usd)
    sign = 1.0 if side == "buy" else -1.0
    price = bar.open * (1.0 + sign * (bar.half_spread + impact_rate))
    return price, bar.half_spread, impact_rate


def fill_orders(
    state: BookState,
    orders: Sequence[PlannedOrder],
    *,
    bars: Mapping[str, FillBar],
    policy: SimulationPolicy,
) -> tuple[BookState, list[SimulatedFill], dict[str, float]]:
    """한 거래일 시가에 주문을 체결한다. 반환: 새 상태, 체결, 종목·방향별 체결 수량."""
    cash = float(state.cash)
    positions = dict(state.positions)
    fills: list[SimulatedFill] = []
    filled: dict[str, float] = {}

    def capacity(bar: FillBar) -> float:
        return policy.max_participation * max(bar.volume, 0.0)

    for order in (item for item in orders if item.side == "sell"):
        bar = bars.get(order.ticker)
        held = positions.get(order.ticker, 0.0)
        if bar is None or held <= 0:
            continue
        quantity = min(order.quantity, held, capacity(bar))
        if quantity < held:
            quantity = _floor(quantity, policy.quantity_decimals)
        if quantity <= 0:
            continue
        price, spread_rate, impact_rate = _execution_price("sell", bar, quantity * bar.open, policy)
        gross = quantity * price
        commission = gross * policy.commission_rate
        cash += gross - commission
        remaining = held - quantity
        if remaining <= _EPSILON:
            positions.pop(order.ticker, None)
        else:
            positions[order.ticker] = remaining
        fills.append(SimulatedFill(order.ticker, "sell", quantity, bar.open, price,
                                   quantity * bar.open * spread_rate, quantity * bar.open * impact_rate, commission))
        filled[f"{order.ticker}:sell"] = quantity

    buys = [item for item in orders if item.side == "buy" and item.ticker in bars]
    wanted = {}
    for order in buys:
        bar = bars[order.ticker]
        wanted[order.ticker] = min(order.quantity, capacity(bar))
    budget = cash * (1.0 - policy.buy_cash_buffer)
    required = 0.0
    for ticker, quantity in wanted.items():
        bar = bars[ticker]
        price, _, _ = _execution_price("buy", bar, quantity * bar.open, policy)
        required += quantity * price * (1.0 + policy.commission_rate)
    scale = 1.0 if required <= budget or required <= 0 else budget / required
    for order in buys:
        bar = bars[order.ticker]
        quantity = _floor(wanted[order.ticker] * scale, policy.quantity_decimals)
        if quantity <= 0 or quantity * bar.open < policy.min_order_notional:
            continue
        price, spread_rate, impact_rate = _execution_price("buy", bar, quantity * bar.open, policy)
        gross = quantity * price
        commission = gross * policy.commission_rate
        if gross + commission > cash + _EPSILON:
            continue
        cash -= gross + commission
        positions[order.ticker] = positions.get(order.ticker, 0.0) + quantity
        fills.append(SimulatedFill(order.ticker, "buy", quantity, bar.open, price,
                                   quantity * bar.open * spread_rate, quantity * bar.open * impact_rate, commission))
        filled[f"{order.ticker}:buy"] = quantity
    return BookState(cash=max(cash, 0.0), positions=positions), fills, filled


def cap_target_weights(
    weights: Mapping[str, float],
    *,
    max_symbol_weight: float,
    min_cash_weight: float,
) -> dict[str, float]:
    """RiskGate를 거치지 않는 challenger 목표비중에 같은 종목 상한·최소 현금만 적용한다.

    한도 없는 후보와 한도 안의 champion을 비교하면 위험을 더 진 쪽이 이겨 보인다.
    넘친 비중은 다른 종목에 다시 나누지 않고 현금으로 보낸다(위험 축소 방향).
    """
    risky = {
        str(ticker).upper(): min(max(float(weight), 0.0), max_symbol_weight)
        for ticker, weight in weights.items()
        if str(ticker).upper() != CASH_SYMBOL and float(weight) > 0
    }
    total = math.fsum(risky.values())
    room = 1.0 - min_cash_weight
    if total > room and total > 0:
        risky = {ticker: weight * room / total for ticker, weight in risky.items()}
    risky[CASH_SYMBOL] = max(0.0, 1.0 - math.fsum(risky.values()))
    return risky


__all__ = [
    "BookState",
    "FillBar",
    "PlannedOrder",
    "SimulatedFill",
    "SimulationPolicy",
    "cap_target_weights",
    "fill_orders",
    "fill_session_date",
    "plan_rebalance",
]
