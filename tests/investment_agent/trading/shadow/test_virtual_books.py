"""가상계좌가 시간축으로 이어지고, 미래 가격·가짜 현금·승인 결과에 기대지 않는지."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from investment_agent.trading.portfolio.contracts import SecurityProposal
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalBook, SignalRecord
from investment_agent.trading.shadow.engine import default_simulation_policy, run_book
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
from investment_agent.trading.shadow.store import VirtualBookStore, book_summary

POLICY = SimulationPolicy(min_order_notional=10.0, quantity_decimals=6, max_participation=0.05,
                          impact_coefficient=1.0, commission_rate=0.0005, buy_cash_buffer=0.0)


def _bar(open_price: float, *, volume: float = 1e9, half_spread: float = 0.0, volatility: float = 0.0) -> FillBar:
    return FillBar("2026-09-15", open_price, volume, half_spread, volatility, 1e12)


class FillSessionTest(unittest.TestCase):
    def test_decision_after_the_open_fills_on_the_next_session(self):
        dates = ["2026-09-14", "2026-09-15"]
        after_open = datetime(2026, 9, 14, 20, tzinfo=timezone.utc)   # 16:00 ET
        before_open = datetime(2026, 9, 14, 13, tzinfo=timezone.utc)  # 09:00 ET
        self.assertEqual(fill_session_date(after_open, dates), "2026-09-15")
        self.assertEqual(fill_session_date(before_open, dates), "2026-09-14")
        self.assertIsNone(fill_session_date(datetime(2026, 9, 15, 20, tzinfo=timezone.utc), dates))


class PlanRebalanceTest(unittest.TestCase):
    def test_sells_come_first_and_tiny_changes_are_not_traded(self):
        state = BookState(cash=1000.0, positions={"AAA": 10.0, "BBB": 5.0})
        orders = plan_rebalance(
            state, prices={"AAA": 100.0, "BBB": 100.0, "CCC": 50.0},
            target_weights={"AAA": 0.0, "BBB": 0.2004, "CCC": 0.5, "CASH": 0.2996}, policy=POLICY,
        )
        self.assertEqual([(o.ticker, o.side) for o in orders], [("AAA", "sell"), ("CCC", "buy")])
        # 전량 청산은 보유 수량 그대로 판다.
        self.assertEqual(orders[0].quantity, 10.0)


class FillOrdersTest(unittest.TestCase):
    def test_sale_proceeds_fund_buys_but_buys_never_exceed_cash(self):
        state = BookState(cash=0.0, positions={"AAA": 10.0})
        orders = [PlannedOrder("AAA", "sell", 10.0, "REBALANCE"), PlannedOrder("BBB", "buy", 20.0, "REBALANCE")]
        new_state, fills, filled = fill_orders(state, orders, bars={"AAA": _bar(100.0), "BBB": _bar(100.0)}, policy=POLICY)
        self.assertNotIn("AAA", new_state.positions)
        # 매도 대금 약 999.5로 20주(2,000)는 못 산다 — 가진 현금만큼만 산다.
        self.assertLess(filled["BBB:buy"], 20.0)
        self.assertGreaterEqual(new_state.cash, 0.0)
        spent = sum(fill.notional + fill.commission for fill in fills if fill.side == "buy")
        received = sum(fill.notional - fill.commission for fill in fills if fill.side == "sell")
        self.assertLessEqual(spent, received + 1e-9)

    def test_participation_limit_leaves_a_partial_fill(self):
        state = BookState(cash=1e6, positions={})
        _, _, filled = fill_orders(state, [PlannedOrder("AAA", "buy", 1000.0, "REBALANCE")],
                                   bars={"AAA": _bar(10.0, volume=2000.0)}, policy=POLICY)
        self.assertEqual(filled["AAA:buy"], 100.0)  # 2,000주 × 5%

    def test_costs_make_buys_dearer_and_sells_cheaper_than_the_open(self):
        bar = FillBar("2026-09-15", 100.0, 1e9, 0.001, 0.02, 1e9)
        _, buys, _ = fill_orders(BookState(cash=1e6), [PlannedOrder("AAA", "buy", 100.0, "R")], bars={"AAA": bar}, policy=POLICY)
        _, sells, _ = fill_orders(BookState(cash=0.0, positions={"AAA": 100.0}), [PlannedOrder("AAA", "sell", 100.0, "R")],
                                  bars={"AAA": bar}, policy=POLICY)
        self.assertGreater(buys[0].fill_price, 100.0)
        self.assertLess(sells[0].fill_price, 100.0)
        self.assertGreater(buys[0].impact_cost, 0.0)
        self.assertAlmostEqual(buys[0].spread_cost, 100.0 * 100.0 * 0.001)


class ChallengerCapTest(unittest.TestCase):
    def test_challenger_weights_get_the_same_symbol_cap_and_cash_floor(self):
        weights = cap_target_weights({"AAA": 0.6, "BBB": 0.3, "CASH": 0.1}, max_symbol_weight=0.1, min_cash_weight=0.05)
        self.assertAlmostEqual(weights["AAA"], 0.1)
        self.assertAlmostEqual(weights["CASH"], 0.8)
        crowded = cap_target_weights({f"T{i}": 0.1 for i in range(10)}, max_symbol_weight=0.1, min_cash_weight=0.05)
        self.assertAlmostEqual(crowded["CASH"], 0.05)


# ---------------------------------------------------------------- engine
DAY = date(2026, 9, 14)


def _rows(open_close: dict[str, tuple[float, float]]) -> list[dict]:
    """과거 40거래일 평탄한 이력 + 지정한 날짜의 시가·종가."""
    rows = []
    for offset in range(40, 0, -1):
        day = DAY - timedelta(days=offset)
        rows.append({"trade_date": day.isoformat(), "open": 100.0, "close": 100.0 * (1 + 0.001 * (offset % 3)),
                     "volume": 10_000_000})
    for trade_date, (open_price, close) in open_close.items():
        rows.append({"trade_date": trade_date, "open": open_price, "close": close, "volume": 10_000_000})
    return rows


class _Repository:
    def __init__(self, prices: dict[str, list[dict]], batch_id: str = "batch-1"):
        self.prices = prices
        self.batch_id = batch_id
        proposal = SecurityProposal(ticker="AAA", as_of_at="2026-09-14T19:00:00+00:00", signal="open",
                                    probability_up=0.6, confidence=0.6, expected_excess_return=0.03,
                                    target_weight=0.1, reasoning=("r",), evidence_ids=("EV-1",))
        batch = SignalBatch(batch_id=batch_id, as_of_at=proposal.as_of_at, completed_at="2026-09-14T19:30:00+00:00",
                            requested_symbols=("AAA",), successful_symbols=("AAA",), failed_symbols=(),
                            model_artifact_id="artifact-1")
        record = SignalRecord(batch_id=batch_id, proposal=proposal, recorded_at="2026-09-14T19:30:00+00:00",
                              expires_at="2026-09-16T19:30:00+00:00", case_key="case")
        self.book = SignalBook(batches=(batch,), records=(record,))

    def market_prices(self, ticker, as_of_at, limit=260):
        return [row for row in self.prices.get(ticker, []) if row["trade_date"] <= as_of_at.date().isoformat()][-limit:]

    def latest_execution_ready_batch_id(self, *, as_of_at):
        return self.batch_id

    def load_signal_book(self, *, as_of_at):
        return self.book


@dataclass
class _Risk:
    approved_weights: dict
    is_approved: bool = True
    risk_decision_id: str = "risk_x"
    violations: tuple = ()
    adjustments: tuple = ()


@dataclass
class _Proposal:
    proposal_id: str = "proposal_x"


@dataclass
class _Evaluation:
    risk: _Risk
    proposal: _Proposal


class VirtualBookEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = VirtualBookStore(Path(self.tmp.name) / "runtime.sqlite3")
        self.store.create_book(book_id="shadow-champion", stage="shadow", policy_kind="optimizer",
                               initial_nav=100_000.0, created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
        # 판단일(9/14) 종가 200, 다음날(9/15) 시가 150 — 체결은 150 근처여야 한다.
        prices = {"2026-09-14": (100.0, 200.0), "2026-09-15": (150.0, 160.0)}
        self.repository = _Repository({"SPY": _rows(prices), "AAA": _rows(prices)})
        self.evaluations = []

    def evaluate(self, repository, **kwargs):
        self.evaluations.append(kwargs)
        return _Evaluation(_Risk({"AAA": 0.5, "CASH": 0.5}), _Proposal())

    def run_at(self, when: datetime):
        return run_book(self.store, self.repository, "shadow-champion", now=when,
                        policy=default_simulation_policy(), evaluate=self.evaluate)

    def test_book_decides_fills_next_open_and_carries_state_forward(self):
        decided = self.run_at(datetime(2026, 9, 14, 23, tzinfo=timezone.utc))  # 9/14 종가 확정 뒤
        self.assertEqual(decided.orders_planned, 1)
        # 판단은 실계좌와 같은 입력 계약으로, 가상계좌 자신을 계좌로 넘긴다.
        self.assertEqual(self.evaluations[0]["expected_account_id"], "shadow-champion")
        self.assertEqual(self.evaluations[0]["stage"], "shadow")
        self.assertEqual(self.evaluations[0]["snapshot"].broker, "virtual")

        waiting = self.run_at(datetime(2026, 9, 15, 16, tzinfo=timezone.utc))  # 9/15 봉 확정 전
        self.assertEqual(waiting.skipped_reason, "orders_pending_fill")
        self.assertIsNone(waiting.settled_session)

        settled = self.run_at(datetime(2026, 9, 15, 23, tzinfo=timezone.utc))
        self.assertEqual(settled.settled_session, "2026-09-15")
        self.assertEqual(settled.skipped_reason, "batch_already_decided")
        state = self.store.state("shadow-champion")
        self.assertIn("AAA", state.positions)
        with self.store._connect() as connection:
            fill_price = connection.execute("SELECT fill_price FROM virtual_fills").fetchone()[0]
        # 판단 당일 종가(200)가 아니라 다음 정규장 시가(150)에 비용을 더한 값이다.
        self.assertGreater(fill_price, 150.0)
        self.assertLess(fill_price, 151.0)
        history = self.store.nav_history("shadow-champion")
        self.assertEqual(history[-1]["trade_date"], "2026-09-15")
        self.assertLess(book_summary(self.store.book("shadow-champion"), history)["nav"], 100_000.0 * 1.2)

    def test_a_new_batch_is_decided_from_the_filled_state_not_the_old_plan(self):
        self.run_at(datetime(2026, 9, 14, 23, tzinfo=timezone.utc))
        self.run_at(datetime(2026, 9, 15, 23, tzinfo=timezone.utc))
        self.repository.batch_id = "batch-2"
        self.repository.book = SignalBook(
            batches=(SignalBatch(batch_id="batch-2", as_of_at="2026-09-14T19:00:00+00:00",
                                 completed_at="2026-09-15T19:30:00+00:00", requested_symbols=("AAA",),
                                 successful_symbols=("AAA",), failed_symbols=(), model_artifact_id="artifact-1"),),
            records=tuple(
                SignalRecord(batch_id="batch-2", proposal=record.proposal, recorded_at=record.recorded_at,
                             expires_at=record.expires_at, case_key=record.case_key)
                for record in self.repository.book.records
            ),
        )
        self.run_at(datetime(2026, 9, 15, 23, 30, tzinfo=timezone.utc))
        snapshot = self.evaluations[-1]["snapshot"]
        self.assertEqual({position.ticker for position in snapshot.positions}, {"AAA"})
        self.assertLess(snapshot.cash_value, 100_000.0)

    def test_virtual_books_do_not_depend_on_any_live_ledger_or_approval(self):
        """승인·거절과 무관하다 — 저장소에 실계좌 기록·승인 메서드가 없어도 끝까지 돈다."""
        for hour in (23,):
            self.run_at(datetime(2026, 9, 14, hour, tzinfo=timezone.utc))
        self.run_at(datetime(2026, 9, 15, 23, tzinfo=timezone.utc))
        self.assertFalse(hasattr(self.repository, "save_portfolio_snapshot"))
        with self.store._connect() as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM account_snapshots").fetchone()[0], 0)
        self.assertIn("virtual_fills", tables)


if __name__ == "__main__":
    unittest.main()
