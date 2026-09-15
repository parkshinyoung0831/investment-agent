"""factor 가상계좌: IC×σ×z 기대수익, LLM 거부권·소폭 조정·검증 전 신규 금지, no-trade band, 재조정 주기."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.research.features.factors import FactorScore
from investment_agent.trading.portfolio.factor_portfolio import (
    FactorBookPolicy,
    FactorSignalPlan,
    LlmView,
    apply_no_trade_band,
    factor_signals,
    rebalance_due,
)

AS_OF = datetime(2026, 9, 15, 21, 0, tzinfo=timezone.utc)
POLICY = FactorBookPolicy(shortlist_size=3)


def _scores(**composites) -> dict[str, FactorScore]:
    return {ticker: FactorScore(ticker, {"quality": 0.8}, value, True, None) for ticker, value in composites.items()}


def _view(ticker: str, action: str, expected: float, probability: float, *, days_ago: int = 3,
          confidence: float = 0.8) -> LlmView:
    return LlmView(ticker, AS_OF - timedelta(days=days_ago), action, expected, probability, confidence)


def _by_symbol(plan: FactorSignalPlan):
    return {signal.symbol: signal for signal in plan.signals}


class FactorSignalsTest(unittest.TestCase):
    def setUp(self):
        self.scores = _scores(TOP=0.9, MID=0.6, LOW=0.2, BOTTOM=0.1, TAIL=0.05)
        self.sigma = {name: 0.08 for name in self.scores}
        self.verified = {name: _view(name, "open", 0.02, 0.6) for name in self.scores}

    def test_expected_return_is_ic_times_sigma_times_z_and_orders_by_score(self):
        plan = factor_signals(self.scores, sigma_by_symbol=self.sigma, held_symbols=[], views={},
                              as_of_at=AS_OF, policy=FactorBookPolicy(shortlist_size=5, llm_tilt_weight=0.0,
                                                                       require_verified_entry=False))
        signals = _by_symbol(plan)
        self.assertGreater(signals["TOP"].expected_return, signals["MID"].expected_return)
        self.assertAlmostEqual(signals["LOW"].expected_return, 0.0, places=12)  # 다섯 중 가운데 순위는 z=0
        self.assertAlmostEqual(signals["TOP"].expected_return, 0.04 * 0.08 * 2.0537489, places=6)  # 백분위 0.98 절단
        self.assertLess(abs(signals["TOP"].expected_return), 0.04 * 0.08 * 2.1)

    def test_only_the_shortlist_and_holdings_enter_the_optimizer(self):
        plan = factor_signals(self.scores, sigma_by_symbol=self.sigma, held_symbols=["TAIL"], views=self.verified,
                              as_of_at=AS_OF, policy=POLICY)
        self.assertEqual(sorted(_by_symbol(plan)), ["LOW", "MID", "TAIL", "TOP"])

    def test_unverified_new_names_cannot_be_bought(self):
        plan = factor_signals(self.scores, sigma_by_symbol=self.sigma, held_symbols=[], views={},
                              as_of_at=AS_OF, policy=POLICY)
        top = _by_symbol(plan)["TOP"]
        self.assertEqual(top.action, "watch")
        self.assertLessEqual(top.expected_return, 0.0)
        self.assertEqual(plan.reasons["TOP"], "UNVERIFIED_ENTRY_BLOCKED")

    def test_expired_view_does_not_verify(self):
        views = {"TOP": _view("TOP", "open", 0.02, 0.6, days_ago=40)}
        plan = factor_signals(self.scores, sigma_by_symbol=self.sigma, held_symbols=[], views=views,
                              as_of_at=AS_OF, policy=POLICY)
        self.assertEqual(plan.reasons["TOP"], "UNVERIFIED_ENTRY_BLOCKED")

    def test_bearish_llm_vetoes_even_a_top_factor_name(self):
        views = {**self.verified, "TOP": _view("TOP", "exit", -0.03, 0.3)}
        plan = factor_signals(self.scores, sigma_by_symbol=self.sigma, held_symbols=["TOP"], views=views,
                              as_of_at=AS_OF, policy=POLICY)
        top = _by_symbol(plan)["TOP"]
        self.assertEqual(top.action, "exit")
        self.assertLess(top.expected_return, 0.0)
        self.assertEqual(plan.reasons["TOP"], "LLM_VETO")

    def test_bullish_llm_cannot_make_a_weak_factor_name_attractive(self):
        views = {"BOTTOM": _view("BOTTOM", "open", 0.20, 0.9, confidence=1.0)}
        plan = factor_signals(self.scores, sigma_by_symbol=self.sigma, held_symbols=["BOTTOM"], views=views,
                              as_of_at=AS_OF, policy=POLICY)
        self.assertLess(_by_symbol(plan)["BOTTOM"].expected_return, 0.0)

    def test_agreeing_llm_tilts_only_partly_and_within_one_sigma(self):
        base = factor_signals(self.scores, sigma_by_symbol=self.sigma, held_symbols=["TOP"], views={},
                              as_of_at=AS_OF, policy=POLICY)
        views = {"TOP": _view("TOP", "hold", 0.50, 0.9, confidence=1.0)}
        tilted = factor_signals(self.scores, sigma_by_symbol=self.sigma, held_symbols=["TOP"], views=views,
                                as_of_at=AS_OF, policy=POLICY)
        before = _by_symbol(base)["TOP"].expected_return
        after = _by_symbol(tilted)["TOP"].expected_return
        # LLM의 +50%는 1σ(8%)로 잘리고 그 25%만 반영된다.
        self.assertAlmostEqual(after, before + 0.25 * (0.08 - before))

    def test_held_name_that_fails_the_quality_gate_can_only_shrink(self):
        scores = {**self.scores, "HELD": FactorScore("HELD", {"quality": 0.1}, 0.95, False, "quality_below_floor")}
        plan = factor_signals(scores, sigma_by_symbol={**self.sigma, "HELD": 0.08}, held_symbols=["HELD"],
                              views={"HELD": _view("HELD", "open", 0.05, 0.7)}, as_of_at=AS_OF, policy=POLICY)
        held = _by_symbol(plan)["HELD"]
        self.assertEqual(held.action, "reduce")
        self.assertLessEqual(held.expected_return, 0.0)

    def test_held_name_without_inputs_is_fixed_not_sold(self):
        plan = factor_signals(self.scores, sigma_by_symbol=self.sigma, held_symbols=["UNKNOWN"], views={},
                              as_of_at=AS_OF, policy=POLICY)
        self.assertEqual(plan.fixed_symbols, ("UNKNOWN",))
        self.assertNotIn("UNKNOWN", _by_symbol(plan))


class FactorExposureConstraintTest(unittest.TestCase):
    def _optimize(self, exposures):
        from investment_agent.trading.portfolio.optimizer import ExpectedReturnSignal, OptimizerPolicy, RiskAwareOptimizer

        signals = [
            ExpectedReturnSignal("MOM", 0.05, 1.0, 0.5, 20, "factor", AS_OF.isoformat(), "t"),
            ExpectedReturnSignal("BAL", 0.01, 1.0, 0.5, 20, "factor", AS_OF.isoformat(), "t"),
        ]
        policy = OptimizerPolicy(turnover_penalty=0.0, max_turnover=1.0, max_symbol_weight=0.5)
        return RiskAwareOptimizer(policy).optimize(
            signals, current_weights={"CASH": 1.0}, covariance=[[0.004, 0.0], [0.0, 0.004]],
            factor_exposures=exposures,
        )

    def test_weighted_average_exposure_is_bounded(self):
        from investment_agent.trading.portfolio.optimizer import FactorExposureLimit

        free = self._optimize(None).weights
        self.assertGreater(free["MOM"], free["BAL"] * 2)
        limit = FactorExposureLimit({"MOM": 1.0, "BAL": 0.5}, maximum=0.7)
        bounded = self._optimize({"momentum": limit}).weights
        average = (bounded["MOM"] * 1.0 + bounded["BAL"] * 0.5) / (bounded["MOM"] + bounded["BAL"])
        self.assertLessEqual(average, 0.7 + 1e-6)

    def test_minimum_exposure_pulls_toward_quality(self):
        from investment_agent.trading.portfolio.optimizer import FactorExposureLimit

        limit = FactorExposureLimit({"MOM": 0.3, "BAL": 0.9}, minimum=0.6)
        weights = self._optimize({"quality": limit}).weights
        average = (weights["MOM"] * 0.3 + weights["BAL"] * 0.9) / (weights["MOM"] + weights["BAL"])
        self.assertGreaterEqual(average, 0.6 - 1e-6)

    def test_missing_loading_is_neutral(self):
        from investment_agent.trading.portfolio.optimizer import FactorExposureLimit

        self.assertEqual(FactorExposureLimit({}, maximum=0.8).loading("X"), 0.5)
        with self.assertRaises(ValueError):
            FactorExposureLimit({}, minimum=0.9, maximum=0.1)


class NoTradeBandTest(unittest.TestCase):
    def test_small_changes_keep_the_current_weight_but_exits_always_happen(self):
        targets = {"AAA": 0.105, "BBB": 0.0, "CCC": 0.20, "CASH": 0.695}
        current = {"AAA": 0.10, "BBB": 0.005, "CCC": 0.05, "CASH": 0.845}
        weights, kept = apply_no_trade_band(targets, current, band=0.01)
        self.assertEqual(weights["AAA"], 0.10)
        self.assertNotIn("BBB", weights)
        self.assertEqual(weights["CCC"], 0.20)
        self.assertEqual(kept, ["AAA"])
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_band_never_creates_negative_cash(self):
        targets = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
        current = {"AAA": 0.509, "BBB": 0.495}
        weights, kept = apply_no_trade_band(targets, current, band=0.01)
        self.assertEqual(kept, [])
        self.assertAlmostEqual(weights["AAA"], 0.5)


class RebalanceCadenceTest(unittest.TestCase):
    def test_same_snapshot_and_recent_decisions_are_skipped(self):
        policy = FactorBookPolicy()
        self.assertEqual(rebalance_due(last_decided_at=None, last_batch_id="factor:S1", snapshot_as_of="S1",
                                       now=AS_OF, policy=policy), "factor_snapshot_already_decided")
        self.assertEqual(rebalance_due(last_decided_at=(AS_OF - timedelta(days=2)).isoformat(), last_batch_id="factor:S0",
                                       snapshot_as_of="S1", now=AS_OF, policy=policy), "rebalance_not_due")
        self.assertIsNone(rebalance_due(last_decided_at=(AS_OF - timedelta(days=8)).isoformat(),
                                        last_batch_id="factor:S0", snapshot_as_of="S1", now=AS_OF, policy=policy))


class LlmViewTest(unittest.TestCase):
    def test_incomplete_decision_rows_are_not_views(self):
        self.assertIsNone(LlmView.from_decision_row("A", None))
        self.assertIsNone(LlmView.from_decision_row("A", {"as_of_at": AS_OF.isoformat(), "final_decision": {"signal": "open"}}))
        view = LlmView.from_decision_row("a", {"as_of_at": AS_OF.isoformat(), "final_decision": {
            "signal": "open", "expected_excess_return": 0.02, "probability_up": 0.6, "confidence": 0.7}})
        self.assertEqual((view.ticker, view.action), ("A", "open"))


# ---------------------------------------------------------------- engine
@dataclass
class _Risk:
    approved_weights: dict
    is_approved: bool = True
    risk_decision_id: str = "risk_f"
    violations: tuple = ()
    adjustments: tuple = ()


@dataclass
class _Proposal:
    proposal_id: str = "proposal_f"
    metadata: dict = None


@dataclass
class _Evaluation:
    risk: _Risk
    proposal: _Proposal


class FactorBookEngineTest(unittest.TestCase):
    def setUp(self):
        from tests.investment_agent.trading.shadow.test_virtual_books import _Repository, _rows
        from investment_agent.trading.shadow.store import VirtualBookStore

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = VirtualBookStore(Path(self.tmp.name) / "runtime.sqlite3")
        self.store.create_book(book_id="shadow-factor", stage="shadow", policy_kind="optimizer",
                               initial_nav=100_000.0, created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                               config={"expected_returns": "factor"})
        prices = {"2026-09-14": (100.0, 200.0), "2026-09-15": (150.0, 160.0)}
        self.repository = _Repository({"SPY": _rows(prices), "AAA": _rows(prices)}, batch_id="llm-batch")
        self.repository.factor_cross_section = lambda now: ("2026-09-14T22:00:00+00:00", _scores(AAA=0.9))
        self.calls = []

    def evaluate_factor(self, repository, **kwargs):
        self.calls.append(kwargs)
        plan = FactorSignalPlan((), (), {"AAA": "FACTOR_BASE"}, {"AAA": {"reason": "FACTOR_BASE"}})
        return _Evaluation(_Risk({"AAA": 0.1, "CASH": 0.9}), _Proposal(metadata={})), plan

    def run_at(self, when):
        from investment_agent.trading.shadow.engine import default_simulation_policy, run_book
        return run_book(self.store, self.repository, "shadow-factor", now=when, policy=default_simulation_policy(),
                        evaluate=lambda *a, **k: self.fail("LLM batch path used"), evaluate_factor=self.evaluate_factor)

    def test_factor_book_decides_from_the_cross_section_not_the_llm_batch(self):
        result = self.run_at(datetime(2026, 9, 14, 23, tzinfo=timezone.utc))
        self.assertEqual(result.orders_planned, 1)
        self.assertEqual(self.calls[0]["snapshot_as_of"], "2026-09-14T22:00:00+00:00")
        self.assertEqual(self.store.book("shadow-factor").last_batch_id, "factor:2026-09-14T22:00:00+00:00")

    def test_factor_book_waits_for_its_rebalance_interval(self):
        self.run_at(datetime(2026, 9, 14, 23, tzinfo=timezone.utc))
        self.run_at(datetime(2026, 9, 15, 23, tzinfo=timezone.utc))  # 체결 정산
        self.repository.factor_cross_section = lambda now: ("2026-09-15T22:00:00+00:00", _scores(AAA=0.9))
        result = self.run_at(datetime(2026, 9, 15, 23, 30, tzinfo=timezone.utc))
        self.assertEqual(result.skipped_reason, "rebalance_not_due")
        self.assertEqual(len(self.calls), 1)

    def test_missing_cross_section_is_a_skip(self):
        self.repository.factor_cross_section = lambda now: None
        result = self.run_at(datetime(2026, 9, 14, 23, tzinfo=timezone.utc))
        self.assertEqual(result.skipped_reason, "no_factor_cross_section")


class EvaluateFactorPortfolioTest(unittest.TestCase):
    """실제 optimizer·RiskGate로 끝까지: 검증된 상위 종목만 사고, 거부된 보유는 팔고, 한도를 지킨다."""

    def test_end_to_end_with_real_optimizer_and_gate(self):
        import math
        import random
        from datetime import date
        from unittest import mock

        from investment_agent.execution.orders.snapshots import AccountSnapshot, PositionSnapshot
        from investment_agent.trading.portfolio.factor_portfolio import evaluate_factor_portfolio

        rng = random.Random(7)
        names = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "SPY", "XLE", "XLF", "XLK", "TLT", "GLD", "HYG", "IEF", "UUP"]
        history: dict[str, list[dict]] = {}
        market = [0.0005 + rng.gauss(0, 0.01) for _ in range(300)]
        for name in names:
            price, rows = 100.0, []
            for offset in range(300):
                price *= 1 + 0.9 * market[offset] + rng.gauss(0, 0.012)
                day = date(2025, 7, 1) + timedelta(days=offset)
                rows.append({"trade_date": day.isoformat(), "open": price, "close": price, "high": price * 1.01,
                             "low": price * 0.99, "volume": 5_000_000})
            history[name] = rows
        now = datetime.combine(date(2025, 7, 1) + timedelta(days=299), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=23)

        class Repository:
            def market_prices(self, ticker, as_of_at, limit=260):
                return history.get(ticker, [])[-limit:]

            def previous_decision(self, ticker, *, as_of_at):
                verdict = {"AAA": ("open", 0.03, 0.65), "BBB": ("open", 0.02, 0.6), "FFF": ("exit", -0.05, 0.3)}.get(ticker)
                if verdict is None:
                    return None
                return {"as_of_at": (as_of_at - timedelta(days=2)).isoformat(), "final_decision": {
                    "signal": verdict[0], "expected_excess_return": verdict[1], "probability_up": verdict[2],
                    "confidence": 0.8}}

            def sp500_sector_map(self, tickers):
                return {ticker: ("tech" if ticker in {"AAA", "BBB", "CCC"} else "energy") for ticker in tickers}

            def current_tracked_tickers(self):
                return ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]

        scores = _scores(AAA=0.95, BBB=0.9, CCC=0.85, DDD=0.3, EEE=0.2, FFF=0.8)
        close = {name: history[name][-1]["close"] for name in names}
        snapshot = AccountSnapshot(
            broker="virtual", account_id="shadow-factor", captured_at=now.isoformat(), cash_value=90_000.0,
            positions=(PositionSnapshot("FFF", 10_000.0 / close["FFF"], close["FFF"], 10_000.0),),
        )
        with mock.patch("investment_agent.trading.portfolio.construct._filled_order_costs", return_value=[]):
            evaluation, plan = evaluate_factor_portfolio(
                Repository(), snapshot=snapshot, stage="shadow", scores=scores,
                snapshot_as_of="S1", policy=FactorBookPolicy(shortlist_size=4),
            )
        weights = evaluation.proposal.weights
        self.assertEqual(plan.reasons["FFF"], "LLM_VETO")
        self.assertAlmostEqual(weights.get("FFF", 0.0), 0.0)            # 거부된 보유는 청산
        self.assertAlmostEqual(weights.get("CCC", 0.0), 0.0)            # 검증 안 된 신규는 못 산다
        self.assertGreater(weights.get("AAA", 0.0), 0.0)                # 검증된 상위 종목은 산다
        self.assertTrue(all(weight <= 0.10 + 1e-6 for symbol, weight in weights.items() if symbol != "CASH"))
        self.assertTrue(math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9))
        self.assertEqual(evaluation.proposal.metadata["factor_snapshot_as_of"], "S1")


class DefaultBooksTest(unittest.TestCase):
    def test_missing_default_books_are_added_without_touching_existing_ones(self):
        from investment_agent.operations.commands.virtual_books import ensure_default_books
        from investment_agent.trading.shadow.store import VirtualBookStore

        with tempfile.TemporaryDirectory() as directory:
            store = VirtualBookStore(Path(directory) / "runtime.sqlite3")
            created = datetime(2026, 9, 1, tzinfo=timezone.utc)
            store.create_book(book_id="shadow-champion", stage="shadow", policy_kind="optimizer",
                              initial_nav=100_000.0, created_at=created)
            ensure_default_books(store, now=AS_OF)
            books = {book.book_id: book for book in store.books()}
            self.assertEqual(books["shadow-champion"].created_at, created.isoformat())
            self.assertEqual(books["shadow-factor-composite"].config, {"expected_returns": "factor"})
            ensure_default_books(store, now=AS_OF)
            self.assertEqual(len(store.books()), 3)


if __name__ == "__main__":
    unittest.main()
