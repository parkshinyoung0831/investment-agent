"""현금·포지션·주문·체결을 소유하는 로컬 simulated broker."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from investment_agent.research.backtest.contracts import (
    BacktestConfig,
    BacktestSafetyError,
    CashEvent,
    CorporateAction,
    CorporateActionApplication,
    FillEvent,
    MarketBar,
    NavPoint,
    OrderEvent,
    PositionSnapshot,
    WeightPoint,
    stable_hash,
)
from investment_agent.research.evaluation.costs import FillQuote, TransactionCostModel
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL

_EPSILON = 1e-10


@dataclass
class _Position:
    quantity: float = 0.0
    cost_basis: float = 0.0

    @property
    def average_cost(self) -> float:
        return self.cost_basis / self.quantity if self.quantity > _EPSILON else 0.0


@dataclass(frozen=True)
class _Candidate:
    symbol: str
    side: str
    quantity: float
    reference_price: float
    quote: FillQuote


class SimulatedBroker:
    """외부 I/O 없이 전량 체결 또는 전체 거부만 수행하는 결정론적 broker다."""

    def __init__(
        self,
        *,
        config: BacktestConfig,
        costs: TransactionCostModel,
        input_hash: str,
        first_session: str,
    ) -> None:
        self.config = config
        self.costs = costs
        self.input_hash = input_hash
        self.cash = config.initial_cash
        self.positions: dict[str, _Position] = {}
        self.orders: list[OrderEvent] = []
        self.fills: list[FillEvent] = []
        self.cash_ledger: list[CashEvent] = []
        self.action_applications: list[CorporateActionApplication] = []
        self.position_snapshots: list[PositionSnapshot] = []
        self.nav_points: list[NavPoint] = []
        self.realized_trade_pnl = 0.0
        self.dividends = 0.0
        self.fees = 0.0
        self.slippage = 0.0
        self._append_cash(
            session_date=first_session,
            kind="initial_cash",
            amount=config.initial_cash,
            symbol=None,
            reference_id=None,
            balance_override=config.initial_cash,
        )

    def _append_cash(
        self,
        *,
        session_date: str,
        kind: str,
        amount: float,
        symbol: str | None,
        reference_id: str | None,
        balance_override: float | None = None,
    ) -> None:
        balance = self.cash if balance_override is None else balance_override
        sequence = len(self.cash_ledger)
        identity = {
            "input_hash": self.input_hash,
            "sequence": sequence,
            "session_date": session_date,
            "kind": kind,
            "amount": amount,
            "balance": balance,
            "symbol": symbol,
            "reference_id": reference_id,
        }
        event_id = f"cash_{stable_hash(identity)[:24]}"
        self.cash_ledger.append(CashEvent(
            event_id=event_id,
            session_date=session_date,
            kind=kind,
            amount=amount,
            balance=balance,
            symbol=symbol,
            reference_id=reference_id,
        ))

    def apply_actions(self, session_date: str, actions: Sequence[CorporateAction]) -> None:
        """같은 날의 split, 지급일 현금배당 순서로 장 시작 전에 적용한다."""
        for action in sorted(
            actions,
            key=lambda item: (item.symbol, item.kind != "split", item.action_id),
        ):
            position = self.positions.get(action.symbol, _Position())
            before = position.quantity
            cash_amount = 0.0
            if action.kind == "split":
                if before > _EPSILON:
                    position.quantity *= action.value
                    self.positions[action.symbol] = position
            elif action.kind == "dividend" and before > _EPSILON:
                cash_amount = before * action.value
                self.cash += cash_amount
                self.dividends += cash_amount
                self._append_cash(
                    session_date=session_date,
                    kind="dividend",
                    amount=cash_amount,
                    symbol=action.symbol,
                    reference_id=action.action_id,
                )
            self.action_applications.append(CorporateActionApplication(
                action_id=action.action_id,
                session_date=session_date,
                symbol=action.symbol,
                kind=action.kind,
                value=action.value,
                quantity_before=before,
                quantity_after=position.quantity,
                cash_amount=cash_amount,
            ))

    def _bar(self, bars: Mapping[str, MarketBar], symbol: str, purpose: str) -> MarketBar:
        bar = bars.get(symbol)
        if bar is None:
            raise BacktestSafetyError(f"missing {purpose} bar for {symbol}")
        return bar

    def _open_nav(self, bars: Mapping[str, MarketBar]) -> float:
        value = self.cash
        for symbol, position in sorted(self.positions.items()):
            if position.quantity <= _EPSILON:
                continue
            value += position.quantity * self._bar(bars, symbol, "open valuation").open
        if not math.isfinite(value) or value <= 0.0:
            raise BacktestSafetyError("pre-trade NAV must be finite and positive")
        return value

    def _quantize_down(self, value: float) -> float:
        scale = 10 ** self.config.quantity_decimals
        return math.floor(max(0.0, value) * scale + 1e-12) / scale

    def rebalance(
        self,
        *,
        session_date: str,
        point: WeightPoint,
        bars: Mapping[str, MarketBar],
        eligible_buy_symbols: set[str],
    ) -> None:
        """전체 목표 비중을 시가 주문으로 바꾸고 원자적으로 전량 체결한다."""
        open_nav = self._open_nav(bars)
        symbols = (
            {symbol for symbol, weight in point.weights.items() if symbol != CASH_SYMBOL and weight > 0.0}
            | {symbol for symbol, position in self.positions.items() if position.quantity > _EPSILON}
        )
        candidates: list[_Candidate] = []
        for symbol in sorted(symbols):
            bar = self._bar(bars, symbol, "rebalance")
            current = self.positions.get(symbol, _Position()).quantity
            target_value = open_nav * point.weights.get(symbol, 0.0)
            target_quantity = self._quantize_down(target_value / bar.open)
            delta = target_quantity - current
            if abs(delta) <= _EPSILON:
                continue
            if bar.halted:
                raise BacktestSafetyError(f"trading is halted for {symbol} on {session_date}")
            side = "buy" if delta > 0.0 else "sell"
            if side == "buy" and symbol not in eligible_buy_symbols:
                raise BacktestSafetyError(
                    f"buy is outside the effective universe on {session_date}: {symbol}"
                )
            quantity = abs(delta)
            if side == "sell" and quantity > current + _EPSILON:
                raise BacktestSafetyError(f"sell quantity exceeds position for {symbol}")
            quote = self.costs.quote(side=side, quantity=quantity, reference_price=bar.open)
            candidates.append(_Candidate(
                symbol=symbol,
                side=side,
                quantity=quantity,
                reference_price=bar.open,
                quote=quote,
            ))

        candidates.sort(key=lambda item: (item.side != "sell", item.symbol))
        projected_cash = self.cash
        for candidate in candidates:
            cash_delta = candidate.quote.gross_notional - candidate.quote.fee
            projected_cash += cash_delta if candidate.side == "sell" else -(
                candidate.quote.gross_notional + candidate.quote.fee
            )
        if projected_cash < -1e-8:
            raise BacktestSafetyError(
                f"rebalance requires unavailable cash: projected balance {projected_cash:.8f}"
            )

        for candidate in candidates:
            self._fill_candidate(session_date=session_date, point=point, candidate=candidate)
        if self.cash < 0.0 and self.cash > -1e-8:
            self.cash = 0.0

    def _fill_candidate(
        self,
        *,
        session_date: str,
        point: WeightPoint,
        candidate: _Candidate,
    ) -> None:
        sequence = len(self.orders)
        identity = {
            "input_hash": self.input_hash,
            "sequence": sequence,
            "point_id": point.point_id,
            "session_date": session_date,
            "symbol": candidate.symbol,
            "side": candidate.side,
            "quantity": candidate.quantity,
        }
        order_id = f"order_{stable_hash(identity)[:24]}"
        fill_identity = {"order_id": order_id, "quote": candidate.quote.__dict__}
        fill_id = f"fill_{stable_hash(fill_identity)[:24]}"
        self.orders.append(OrderEvent(
            order_id=order_id,
            point_id=point.point_id,
            session_date=session_date,
            symbol=candidate.symbol,
            side=candidate.side,
            quantity=candidate.quantity,
            reference_price=candidate.reference_price,
        ))
        self.fills.append(FillEvent(
            fill_id=fill_id,
            order_id=order_id,
            session_date=session_date,
            symbol=candidate.symbol,
            side=candidate.side,
            quantity=candidate.quantity,
            reference_price=candidate.reference_price,
            fill_price=candidate.quote.fill_price,
            gross_notional=candidate.quote.gross_notional,
            fee=candidate.quote.fee,
            slippage_cost=candidate.quote.slippage_cost,
        ))

        position = self.positions.setdefault(candidate.symbol, _Position())
        if candidate.side == "buy":
            self.cash -= candidate.quote.gross_notional
            self._append_cash(
                session_date=session_date,
                kind="buy",
                amount=-candidate.quote.gross_notional,
                symbol=candidate.symbol,
                reference_id=fill_id,
            )
            self.cash -= candidate.quote.fee
            position.quantity += candidate.quantity
            position.cost_basis += candidate.quote.gross_notional + candidate.quote.fee
        else:
            fraction = min(1.0, candidate.quantity / position.quantity)
            allocated_basis = position.cost_basis * fraction
            self.cash += candidate.quote.gross_notional
            self._append_cash(
                session_date=session_date,
                kind="sell",
                amount=candidate.quote.gross_notional,
                symbol=candidate.symbol,
                reference_id=fill_id,
            )
            self.cash -= candidate.quote.fee
            self.realized_trade_pnl += (
                candidate.quote.gross_notional - candidate.quote.fee - allocated_basis
            )
            position.quantity -= candidate.quantity
            position.cost_basis -= allocated_basis
            if position.quantity <= _EPSILON:
                position.quantity = 0.0
                position.cost_basis = 0.0
        if candidate.quote.fee > 0.0:
            self._append_cash(
                session_date=session_date,
                kind="fee",
                amount=-candidate.quote.fee,
                symbol=candidate.symbol,
                reference_id=fill_id,
            )
        self.fees += candidate.quote.fee
        self.slippage += candidate.quote.slippage_cost

    def mark_close(self, session_date: str, bars: Mapping[str, MarketBar]) -> None:
        """종가로 보유분과 NAV·PnL을 완전하게 평가한다."""
        market_value = 0.0
        unrealized = 0.0
        for symbol, position in sorted(self.positions.items()):
            if position.quantity <= _EPSILON:
                continue
            bar = self._bar(bars, symbol, "close valuation")
            if bar.halted:
                raise BacktestSafetyError(
                    f"halted close valuation has no explicit mark policy for {symbol} on {session_date}"
                )
            value = position.quantity * bar.close
            position_unrealized = value - position.cost_basis
            market_value += value
            unrealized += position_unrealized
            self.position_snapshots.append(PositionSnapshot(
                session_date=session_date,
                symbol=symbol,
                quantity=position.quantity,
                average_cost=position.average_cost,
                cost_basis=position.cost_basis,
                market_price=bar.close,
                market_value=value,
                unrealized_pnl=position_unrealized,
            ))
        nav = self.cash + market_value
        if not math.isfinite(nav) or nav <= 0.0:
            raise BacktestSafetyError("close NAV must be finite and positive")
        realized = self.realized_trade_pnl + self.dividends
        total_pnl = realized + unrealized
        accounting_pnl = nav - self.config.initial_cash
        if not math.isclose(total_pnl, accounting_pnl, abs_tol=1e-6, rel_tol=1e-10):
            raise BacktestSafetyError("portfolio accounting identity does not reconcile")
        self.nav_points.append(NavPoint(
            session_date=session_date,
            cash=self.cash,
            market_value=market_value,
            nav=nav,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            total_pnl=total_pnl,
            dividends=self.dividends,
            fees=self.fees,
            slippage=self.slippage,
            gross_exposure=market_value / nav,
        ))
