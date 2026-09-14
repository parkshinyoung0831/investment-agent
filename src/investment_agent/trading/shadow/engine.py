"""가상계좌를 시간축으로 이어 운영한다: 체결 정산 → 평가 → 새 신호가 있으면 재판단.

## 판단은 실계좌와 같은 함수가 한다

optimizer 가상계좌는 `construct.evaluate_portfolio`를 그대로 부른다. 입력만 토스 계좌 대신
가상계좌 상태다. 판단 경로가 달라지면 Shadow 성과는 실계좌가 할 일을 증명하지 못한다.
`paper` 단계는 같은 함수를 `stage="paper"`로 불러 승격 확인과 fail-closed 입력 검사를 받는다.

## 한 번에 한 판단

체결되지 않은 주문이 남아 있으면 새 판단을 하지 않는다. 부분체결로 남은 수량을 들고 옛 계획을
이어 사지 않고, 체결이 끝난 실제 상태에서 다음 판단이 다시 계산한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from investment_agent.data.market.domain.calendar import bar_available_at
from investment_agent.execution.orders.planning import ExecutionLimits
from investment_agent.execution.orders.snapshots import AccountSnapshot, PositionSnapshot
from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import stable_id
from investment_agent.research.evaluation.costs import TransactionCostModel
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL
from investment_agent.trading.portfolio.market_risk import estimate_trading_costs
from investment_agent.trading.portfolio.optimizer import OptimizerPolicy
from investment_agent.trading.risk.gate import PortfolioRiskPolicy
from investment_agent.trading.shadow.simulator import (
    BookState,
    FillBar,
    PlannedOrder,
    SimulationPolicy,
    cap_target_weights,
    fill_orders,
    fill_session_date,
    plan_rebalance,
)
from investment_agent.trading.shadow.store import VirtualBook, VirtualBookStore

log = get_logger(__name__)

CALENDAR_SYMBOL = "SPY"
_PRICE_ROWS = 130


def default_simulation_policy() -> SimulationPolicy:
    """실계좌 경로의 주문 한도·optimizer 비용 가정·백테스트 수수료와 같은 값."""
    limits = ExecutionLimits()
    optimizer = OptimizerPolicy()
    return SimulationPolicy(
        min_order_notional=limits.min_order_notional,
        quantity_decimals=limits.quantity_decimals,
        max_participation=optimizer.max_adv_participation,
        impact_coefficient=optimizer.impact_coefficient,
        commission_rate=TransactionCostModel().commission_rate,
    )


@dataclass(frozen=True)
class BookRunResult:
    book_id: str
    settled_session: str | None = None
    marked_session: str | None = None
    nav: float | None = None
    decision_id: str | None = None
    orders_planned: int = 0
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _finalized_rows(repository: Any, ticker: str, now: datetime) -> list[dict]:
    rows = repository.market_prices(ticker, now, limit=_PRICE_ROWS)
    return sorted(
        (row for row in rows if row.get("close") and bar_available_at(str(row["trade_date"])) <= now),
        key=lambda row: str(row["trade_date"]),
    )


def _latest_closes(repository: Any, tickers: set[str], now: datetime) -> dict[str, float]:
    prices: dict[str, float] = {}
    for ticker in sorted(tickers):
        rows = _finalized_rows(repository, ticker, now)
        if rows:
            prices[ticker] = float(rows[-1]["close"])
    return prices


def settle_pending_orders(
    store: VirtualBookStore,
    book: VirtualBook,
    repository: Any,
    *,
    now: datetime,
    policy: SimulationPolicy,
) -> str | None:
    """판단 뒤 첫 정규장 시가 봉이 확정됐으면 대기 주문을 체결·마감한다. 반환: 체결 거래일."""
    pending = store.pending_orders(book.book_id)
    if not pending:
        return None
    decided_at = min(datetime.fromisoformat(order["created_at"]) for order in pending)
    calendar = [str(row["trade_date"]) for row in _finalized_rows(repository, CALENDAR_SYMBOL, now)]
    session = fill_session_date(decided_at, calendar)
    if session is None:
        return None
    bars: dict[str, FillBar] = {}
    unavailable: dict[str, str] = {}
    for ticker in sorted({order["ticker"] for order in pending}):
        rows = repository.market_prices(ticker, now, limit=_PRICE_ROWS)
        on_session = [row for row in rows if str(row["trade_date"]) == session]
        history = [row for row in rows if str(row["trade_date"]) < session]
        if not on_session or not on_session[0].get("open"):
            # 거래정지·상장폐지·데이터 공백. 추정 가격으로 체결하지 않는다.
            unavailable[ticker] = "no_bar_on_fill_session"
            continue
        try:
            costs = estimate_trading_costs({ticker: history}, symbols=(ticker,))[ticker]
        except ContractError:
            unavailable[ticker] = "cost_inputs_unavailable"
            continue
        bar = on_session[0]
        bars[ticker] = FillBar(session, float(bar["open"]), float(bar.get("volume") or 0.0),
                               costs.half_spread, costs.daily_volatility, costs.adv_usd)
    orders = [PlannedOrder(order["ticker"], order["side"], order["requested_quantity"], order["reason_code"])
              for order in pending]
    state, fills, filled = fill_orders(store.state(book.book_id), orders, bars=bars, policy=policy)
    order_ids = {(order["ticker"], order["side"]): order["order_id"] for order in pending}
    results: dict[str, tuple[float, str]] = {}
    for order in pending:
        quantity = filled.get(f"{order['ticker']}:{order['side']}", 0.0)
        if quantity >= order["requested_quantity"] - 1e-9:
            status = "filled"
        elif quantity > 0:
            status = "partially_filled"
        else:
            status = "cancelled"
        results[order["order_id"]] = (quantity, status)
    reasons = sorted(set(unavailable.values()))
    store.apply_session(
        book_id=book.book_id,
        trade_date=session,
        closed_at=now,
        state=state,
        fills=[
            {
                "fill_id": stable_id("virtual_fill", {"order_id": order_ids[(fill.ticker, fill.side)], "session": session}),
                "order_id": order_ids[(fill.ticker, fill.side)],
                "ticker": fill.ticker, "side": fill.side, "quantity": fill.quantity,
                "reference_price": fill.reference_price, "fill_price": fill.fill_price,
                "spread_cost": fill.spread_cost, "impact_cost": fill.impact_cost, "commission": fill.commission,
            }
            for fill in fills
        ],
        order_results=results,
        cancelled_reason=",".join(reasons) if reasons else "participation_or_cash_limit",
    )
    return session


def mark_book(store: VirtualBookStore, book: VirtualBook, repository: Any, *, now: datetime) -> tuple[str, float] | None:
    """가장 최근 확정 거래일 종가로 가상계좌 가치를 기록한다."""
    calendar = _finalized_rows(repository, CALENDAR_SYMBOL, now)
    if not calendar:
        return None
    session = str(calendar[-1]["trade_date"])
    state = store.state(book.book_id)
    closes: dict[str, float] = {}
    for ticker in state.positions:
        rows = [row for row in _finalized_rows(repository, ticker, now) if str(row["trade_date"]) <= session]
        if not rows:
            raise ContractError(f"no finalized close to value {ticker} in book {book.book_id}")
        closes[ticker] = float(rows[-1]["close"])
    nav = state.nav(closes)
    exposure = sum(quantity * closes[ticker] for ticker, quantity in state.positions.items())
    store.record_nav(book_id=book.book_id, trade_date=session, nav=nav, cash=state.cash,
                     gross_exposure=exposure / nav if nav > 0 else 0.0)
    return session, nav


def _virtual_snapshot(book: VirtualBook, state: BookState, prices: Mapping[str, float], now: datetime) -> AccountSnapshot:
    return AccountSnapshot(
        broker="virtual",
        account_id=book.book_id,
        captured_at=now.isoformat(),
        cash_value=state.cash,
        positions=tuple(
            PositionSnapshot(ticker, quantity, prices[ticker], quantity * prices[ticker])
            for ticker, quantity in sorted(state.positions.items())
        ),
    )


def _optimizer_targets(repository: Any, book: VirtualBook, snapshot: AccountSnapshot, batch_id: str,
                       evaluate: Callable[..., Any]) -> tuple[dict[str, float] | None, dict[str, str], dict[str, Any]]:
    signal_book = repository.load_signal_book(as_of_at=datetime.fromisoformat(snapshot.captured_at))
    evaluation = evaluate(
        repository, signal_book=signal_book, active_batch_id=batch_id, snapshot=snapshot,
        expected_account_id=book.book_id, stage=book.stage,
    )
    risk = evaluation.risk
    signals = {record.proposal.ticker: record.proposal.signal for record in signal_book.records
               if record.batch_id == batch_id}
    reasons = {ticker: "EXIT_SIGNAL" for ticker, signal in signals.items() if signal == "exit"}
    detail = {
        "proposal_id": evaluation.proposal.proposal_id,
        "risk_decision_id": risk.risk_decision_id,
        "violations": list(risk.violations),
        "adjustments": list(risk.adjustments),
    }
    return (dict(risk.approved_weights) if risk.is_approved else None), reasons, detail


def _rl_targets(repository: Any, book: VirtualBook, snapshot: AccountSnapshot, batch_id: str) -> tuple[dict[str, float] | None, dict[str, str], dict[str, Any]]:
    from investment_agent.research.rl.serving import compute_rl_target_weights, default_active_policy_path

    signal_book = repository.load_signal_book(as_of_at=datetime.fromisoformat(snapshot.captured_at))
    proposals = [record.proposal for record in signal_book.records if record.batch_id == batch_id]
    path = Path(book.config.get("policy_path") or default_active_policy_path())
    outcome = compute_rl_target_weights(
        repository, as_of_at=snapshot.captured_at, policy_path=path, proposals=proposals,
        current_weights=snapshot.weights,
    )
    detail = {**outcome.log_payload()}
    if not outcome.available:
        return None, {}, detail
    limits = PortfolioRiskPolicy()
    weights = cap_target_weights(outcome.weights, max_symbol_weight=limits.max_symbol_weight,
                                 min_cash_weight=limits.min_cash_weight)
    return weights, {}, detail


def run_book(
    store: VirtualBookStore,
    repository: Any,
    book_id: str,
    *,
    now: datetime,
    policy: SimulationPolicy | None = None,
    evaluate: Callable[..., Any] | None = None,
) -> BookRunResult:
    """정산 → 평가 → (새 배치가 있으면) 판단과 주문 계획. 실주문·실계좌 원장에는 닿지 않는다."""
    if evaluate is None:
        from investment_agent.trading.portfolio.construct import evaluate_portfolio as evaluate
    selected_policy = policy or default_simulation_policy()
    book = store.book(book_id)
    settled = settle_pending_orders(store, book, repository, now=now, policy=selected_policy)
    marked = mark_book(store, book, repository, now=now)
    base = {"book_id": book_id, "settled_session": settled,
            "marked_session": marked[0] if marked else None, "nav": marked[1] if marked else None}
    if store.pending_orders(book_id):
        return BookRunResult(**base, skipped_reason="orders_pending_fill")
    # 실계좌 경로와 같은 배치 선택: 완전하고 만료되지 않은 배치만. 일부 종목이 실패한 배치로
    # 판단하면 실계좌가 할 수 없는 판단을 가상계좌만 해 성과 비교가 어긋난다.
    batch_id = repository.latest_execution_ready_batch_id(as_of_at=now)
    if batch_id is None:
        return BookRunResult(**base, skipped_reason="no_execution_ready_batch")
    if batch_id == book.last_batch_id:
        return BookRunResult(**base, skipped_reason="batch_already_decided")
    state = store.state(book_id)
    signal_symbols = {record.proposal.ticker for record in repository.load_signal_book(as_of_at=now).records
                      if record.batch_id == batch_id}
    prices = _latest_closes(repository, set(state.positions) | signal_symbols, now)
    missing = sorted(set(state.positions) - set(prices))
    if missing:
        return BookRunResult(**base, skipped_reason=f"held_positions_without_price:{','.join(missing)}")
    snapshot = _virtual_snapshot(book, state, prices, now)
    if book.policy_kind == "optimizer":
        targets, reasons, detail = _optimizer_targets(repository, book, snapshot, batch_id, evaluate)
    else:
        targets, reasons, detail = _rl_targets(repository, book, snapshot, batch_id)
    nav = state.nav(prices)
    decision_id = stable_id("virtual_decision", {"book_id": book_id, "batch_id": batch_id})
    planned: list[PlannedOrder] = []
    if targets is not None:
        tradable = {ticker: weight for ticker, weight in targets.items() if ticker == CASH_SYMBOL or ticker in prices}
        dropped = sorted(set(targets) - set(tradable))
        if dropped:
            detail = {**detail, "targets_without_price": dropped}
        planned = plan_rebalance(state, prices=prices, target_weights=tradable, policy=selected_policy,
                                 reason_codes=reasons)
    store.record_decision(
        book_id=book_id, decision_id=decision_id, batch_id=batch_id, decided_at=now,
        proposal_id=detail.get("proposal_id"), risk_decision_id=detail.get("risk_decision_id"),
        is_approved=targets is not None, nav=nav, target_weights=targets or {}, detail=detail,
        orders=[
            {"order_id": stable_id("virtual_order", {"decision_id": decision_id, "ticker": order.ticker, "side": order.side}),
             "ticker": order.ticker, "side": order.side, "quantity": order.quantity, "reason_code": order.reason_code}
            for order in planned
        ],
    )
    log.info("virtual book decided book=%s batch=%s approved=%s orders=%d",
             book_id, batch_id, targets is not None, len(planned))
    return BookRunResult(**base, decision_id=decision_id, orders_planned=len(planned))


__all__ = ["BookRunResult", "default_simulation_policy", "mark_book", "run_book", "settle_pending_orders"]
