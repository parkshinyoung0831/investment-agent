"""가상계좌 원장(로컬 SQLite `virtual_*` 표)의 읽기·쓰기 경계."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.shadow.simulator import BookState

STAGES = ("shadow", "paper")
POLICY_KINDS = ("optimizer", "rl_policy")


@dataclass(frozen=True)
class VirtualBook:
    book_id: str
    stage: str
    policy_kind: str
    initial_nav: float
    cash: float
    created_at: str
    last_batch_id: str | None
    last_decided_at: str | None
    config: Mapping[str, Any]


class VirtualBookStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = path

    def _connect(self, *, read_only: bool = False):
        return runtime_connection(self.path, read_only=read_only)

    def create_book(self, *, book_id: str, stage: str, policy_kind: str, initial_nav: float,
                    created_at: datetime, config: Mapping[str, Any] | None = None) -> VirtualBook:
        if stage not in STAGES:
            raise ContractError(f"virtual book stage must be one of {STAGES}")
        if policy_kind not in POLICY_KINDS:
            raise ContractError(f"virtual book policy must be one of {POLICY_KINDS}")
        if not initial_nav > 0:
            raise ContractError("initial_nav must be positive")
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM virtual_books WHERE book_id=?", (book_id,)).fetchone():
                raise ContractError(f"virtual book already exists: {book_id}")
            connection.execute(
                "INSERT INTO virtual_books(book_id,stage,policy_kind,initial_nav,cash,created_at,config_json)"
                " VALUES(?,?,?,?,?,?,?)",
                (book_id, stage, policy_kind, float(initial_nav), float(initial_nav),
                 created_at.isoformat(), canonical_json(dict(config or {}))),
            )
        return self.book(book_id)

    def books(self) -> list[VirtualBook]:
        with self._connect() as connection:
            rows = connection.execute("SELECT book_id FROM virtual_books ORDER BY book_id").fetchall()
        return [self.book(str(row[0])) for row in rows]

    def book(self, book_id: str) -> VirtualBook:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT book_id,stage,policy_kind,initial_nav,cash,created_at,last_batch_id,last_decided_at,config_json"
                " FROM virtual_books WHERE book_id=?", (book_id,),
            ).fetchone()
        if row is None:
            raise ContractError(f"unknown virtual book: {book_id}")
        return VirtualBook(str(row[0]), str(row[1]), str(row[2]), float(row[3]), float(row[4]), str(row[5]),
                           row[6], row[7], json.loads(row[8]))

    def state(self, book_id: str) -> BookState:
        book = self.book(book_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT ticker,quantity FROM virtual_positions WHERE book_id=?", (book_id,),
            ).fetchall()
        return BookState(cash=book.cash, positions={str(ticker): float(quantity) for ticker, quantity in rows})

    def cost_basis(self, book_id: str) -> dict[str, float]:
        with self._connect() as connection:
            rows = connection.execute("SELECT ticker,cost_basis FROM virtual_positions WHERE book_id=?", (book_id,)).fetchall()
        return {str(ticker): float(basis) for ticker, basis in rows}

    def pending_orders(self, book_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT order_id,decision_id,ticker,side,requested_quantity,reason_code,created_at"
                " FROM virtual_orders WHERE book_id=? AND status='pending' ORDER BY created_at,order_id",
                (book_id,),
            ).fetchall()
        return [
            {"order_id": row[0], "decision_id": row[1], "ticker": row[2], "side": row[3],
             "requested_quantity": float(row[4]), "reason_code": row[5], "created_at": row[6]}
            for row in rows
        ]

    def record_decision(self, *, book_id: str, decision_id: str, batch_id: str, decided_at: datetime,
                        proposal_id: str | None, risk_decision_id: str | None, is_approved: bool, nav: float,
                        target_weights: Mapping[str, float], detail: Mapping[str, Any],
                        orders: Iterable[Mapping[str, Any]]) -> None:
        """판단·주문·배치 선점을 한 트랜잭션으로 남긴다. 같은 판단을 두 번 기록하지 않는다."""
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM virtual_decisions WHERE decision_id=?", (decision_id,)).fetchone():
                return
            connection.execute(
                "INSERT INTO virtual_decisions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (decision_id, book_id, batch_id, decided_at.isoformat(), proposal_id, risk_decision_id,
                 int(bool(is_approved)), float(nav), canonical_json(dict(target_weights)), canonical_json(dict(detail))),
            )
            for order in orders:
                connection.execute(
                    "INSERT INTO virtual_orders(order_id,book_id,decision_id,ticker,side,requested_quantity,status,"
                    "reason_code,created_at) VALUES(?,?,?,?,?,?, 'pending',?,?)",
                    (order["order_id"], book_id, decision_id, order["ticker"], order["side"],
                     float(order["quantity"]), order["reason_code"], decided_at.isoformat()),
                )
            connection.execute(
                "UPDATE virtual_books SET last_batch_id=?, last_decided_at=? WHERE book_id=?",
                (batch_id, decided_at.isoformat(), book_id),
            )

    def apply_session(self, *, book_id: str, trade_date: str, closed_at: datetime, state: BookState,
                      fills: Iterable[Mapping[str, Any]], order_results: Mapping[str, tuple[float, str]],
                      cancelled_reason: str | None = None) -> None:
        """한 거래일 체결 결과(상태·체결·주문 마감)를 원자적으로 반영한다."""
        fills = list(fills)
        with self._connect() as connection:
            basis = {str(t): float(b) for t, b in connection.execute(
                "SELECT ticker,cost_basis FROM virtual_positions WHERE book_id=?", (book_id,)).fetchall()}
            held = {str(t): float(q) for t, q in connection.execute(
                "SELECT ticker,quantity FROM virtual_positions WHERE book_id=?", (book_id,)).fetchall()}
            for fill in fills:
                connection.execute(
                    "INSERT INTO virtual_fills VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (fill["fill_id"], fill["order_id"], book_id, fill["ticker"], fill["side"], trade_date,
                     fill["quantity"], fill["reference_price"], fill["fill_price"], fill["spread_cost"],
                     fill["impact_cost"], fill["commission"]),
                )
                ticker = fill["ticker"]
                if fill["side"] == "buy":
                    basis[ticker] = basis.get(ticker, 0.0) + fill["quantity"] * fill["fill_price"] + fill["commission"]
                elif held.get(ticker, 0.0) > 0:
                    basis[ticker] = basis.get(ticker, 0.0) * max(0.0, 1.0 - fill["quantity"] / held[ticker])
                held[ticker] = held.get(ticker, 0.0) + (fill["quantity"] if fill["side"] == "buy" else -fill["quantity"])
            for order_id, (filled_quantity, status) in order_results.items():
                connection.execute(
                    "UPDATE virtual_orders SET filled_quantity=?, status=?, closed_at=?, close_reason=?"
                    " WHERE order_id=? AND status='pending'",
                    (float(filled_quantity), status, closed_at.isoformat(),
                     cancelled_reason if status != "filled" else None, order_id),
                )
            connection.execute("DELETE FROM virtual_positions WHERE book_id=?", (book_id,))
            for ticker, quantity in sorted(state.positions.items()):
                connection.execute(
                    "INSERT INTO virtual_positions VALUES(?,?,?,?)",
                    (book_id, ticker, float(quantity), max(0.0, basis.get(ticker, 0.0))),
                )
            connection.execute("UPDATE virtual_books SET cash=? WHERE book_id=?", (float(state.cash), book_id))

    def record_nav(self, *, book_id: str, trade_date: str, nav: float, cash: float, gross_exposure: float) -> None:
        with self._connect() as connection:
            traded, cost = connection.execute(
                "SELECT COALESCE(SUM(quantity*fill_price),0), COALESCE(SUM(spread_cost+impact_cost+commission),0)"
                " FROM virtual_fills WHERE book_id=? AND trade_date=?", (book_id, trade_date),
            ).fetchone()
            connection.execute(
                "INSERT INTO virtual_nav VALUES(?,?,?,?,?,?,?) ON CONFLICT(book_id,trade_date) DO UPDATE SET"
                " nav=excluded.nav, cash=excluded.cash, gross_exposure=excluded.gross_exposure,"
                " traded_notional=excluded.traded_notional, cost=excluded.cost",
                (book_id, trade_date, float(nav), float(cash), float(gross_exposure), float(traded), float(cost)),
            )

    def nav_history(self, book_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT trade_date,nav,cash,gross_exposure,traded_notional,cost FROM virtual_nav"
                " WHERE book_id=? ORDER BY trade_date", (book_id,),
            ).fetchall()
        return [dict(zip(("trade_date", "nav", "cash", "gross_exposure", "traded_notional", "cost"), row)) for row in rows]


def book_summary(book: VirtualBook, history: list[Mapping[str, Any]]) -> dict[str, Any]:
    """누적 수익·최대 낙폭·회전율·비용. 성과 비교의 공통 요약이다."""
    if not history:
        return {"book_id": book.book_id, "days": 0}
    peak = book.initial_nav
    max_drawdown = 0.0
    for row in history:
        peak = max(peak, float(row["nav"]))
        if peak > 0:
            max_drawdown = max(max_drawdown, 1.0 - float(row["nav"]) / peak)
    traded = sum(float(row["traded_notional"]) for row in history)
    average_nav = sum(float(row["nav"]) for row in history) / len(history)
    return {
        "book_id": book.book_id,
        "stage": book.stage,
        "policy_kind": book.policy_kind,
        "days": len(history),
        "nav": float(history[-1]["nav"]),
        "total_return": float(history[-1]["nav"]) / book.initial_nav - 1.0,
        "max_drawdown": max_drawdown,
        "turnover": traded / average_nav if average_nav > 0 else 0.0,
        "total_cost": sum(float(row["cost"]) for row in history),
    }


__all__ = ["POLICY_KINDS", "STAGES", "VirtualBook", "VirtualBookStore", "book_summary"]
