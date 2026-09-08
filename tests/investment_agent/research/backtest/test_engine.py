from __future__ import annotations

import unittest

from investment_agent.research.backtest.contracts import (
    BacktestConfig,
    BacktestRequest,
    BacktestSafetyError,
    CorporateAction,
    MarketBar,
    UniverseSnapshot,
    WeightPoint,
)
from investment_agent.research.evaluation.costs import TransactionCostModel
from investment_agent.research.backtest.engine import run_backtest


def market_bar(
    session_date: str,
    *,
    symbol: str = "AAPL",
    open_price: float = 100.0,
    close_price: float | None = None,
    halted: bool = False,
) -> MarketBar:
    close = open_price if close_price is None else close_price
    return MarketBar(
        symbol=symbol,
        session_date=session_date,
        open=open_price,
        high=max(open_price, close),
        low=min(open_price, close),
        close=close,
        volume=0.0 if halted else 1_000.0,
        halted=halted,
    )


def weight_point(
    decided_at: str = "2026-01-02T21:00:00Z",
    effective_date: str = "2026-01-03",
    weights: dict[str, float] | None = None,
) -> WeightPoint:
    return WeightPoint.create(
        decided_at=decided_at,
        effective_date=effective_date,
        weights=weights or {"AAPL": 0.5, "CASH": 0.5},
        source_id=f"proposal-{effective_date}",
    )


def request(
    *,
    bars: tuple[MarketBar, ...],
    points: tuple[WeightPoint, ...] | None = None,
    actions: tuple[CorporateAction, ...] = (),
    cohort_mode: str = "point_in_time",
    universe: tuple[str, ...] = ("AAPL",),
) -> BacktestRequest:
    snapshot_date = "2026-08-01" if cohort_mode == "current_cohort" else "2026-01-01"
    return BacktestRequest(
        sessions=tuple(sorted({item.session_date for item in bars})),
        bars=bars,
        weight_points=points or (weight_point(),),
        universe_snapshots=(UniverseSnapshot(snapshot_date, universe, "membership"),),
        corporate_actions=actions,
        config=BacktestConfig(initial_cash=1_000.0, cohort_mode=cohort_mode),
    )


ZERO_COST = TransactionCostModel(
    commission_rate=0.0,
    minimum_commission=0.0,
    slippage_bps=0.0,
    sell_fee_rate=0.0,
)


class BacktestEngineTest(unittest.TestCase):
    def test_decision_is_filled_only_at_next_session_open(self):
        result = run_backtest(request(bars=(
            market_bar("2026-01-02", open_price=90.0, close_price=95.0),
            market_bar("2026-01-03", open_price=100.0, close_price=110.0),
        )), costs=ZERO_COST)

        self.assertEqual(len(result.orders), 1)
        self.assertEqual(result.orders[0].session_date, "2026-01-03")
        self.assertEqual(result.orders[0].quantity, 5.0)
        self.assertEqual(result.nav[0].nav, 1_000.0)
        self.assertEqual(result.nav[-1].cash, 500.0)
        self.assertEqual(result.nav[-1].market_value, 550.0)
        self.assertAlmostEqual(result.metrics["total_return"], 0.05)

    def test_wrong_effective_session_is_rejected_as_lookahead_boundary(self):
        wrong = weight_point(
            decided_at="2026-01-01T21:00:00Z",
            effective_date="2026-01-03",
        )
        with self.assertRaisesRegex(BacktestSafetyError, r"t\+1 session 2026-01-02"):
            run_backtest(request(
                bars=(market_bar("2026-01-02"), market_bar("2026-01-03")),
                points=(wrong,),
            ), costs=ZERO_COST)

    def test_explicit_calendar_exposes_an_entire_missing_market_day(self):
        late = weight_point(
            decided_at="2026-01-02T21:00:00Z",
            effective_date="2026-01-04",
        )
        missing_t_plus_one = BacktestRequest(
            sessions=("2026-01-02", "2026-01-03", "2026-01-04"),
            bars=(market_bar("2026-01-02"), market_bar("2026-01-04")),
            weight_points=(late,),
            universe_snapshots=(
                UniverseSnapshot("2026-01-01", ("AAPL",), "membership"),
            ),
            config=BacktestConfig(initial_cash=1_000.0),
        )
        with self.assertRaisesRegex(BacktestSafetyError, r"t\+1 session 2026-01-03"):
            run_backtest(missing_t_plus_one, costs=ZERO_COST)

    def test_fees_and_slippage_flow_through_cash_nav_and_pnl(self):
        costs = TransactionCostModel(commission_rate=0.01, slippage_bps=100.0)
        result = run_backtest(request(bars=(
            market_bar("2026-01-02"),
            market_bar("2026-01-03", open_price=100.0, close_price=100.0),
        )), costs=costs)
        fill = result.fills[0]
        self.assertEqual(fill.fill_price, 101.0)
        self.assertAlmostEqual(fill.gross_notional, 505.0)
        self.assertAlmostEqual(fill.fee, 5.05)
        self.assertAlmostEqual(fill.slippage_cost, 5.0)
        self.assertAlmostEqual(result.nav[-1].nav, 989.95)
        self.assertAlmostEqual(result.nav[-1].total_pnl, -10.05)
        self.assertAlmostEqual(result.metrics["total_fees"], 5.05)

    def test_split_and_dividend_are_applied_before_open(self):
        actions = (
            CorporateAction("AAPL", "2026-01-04", "dividend", 1.0),
            CorporateAction("AAPL", "2026-01-04", "split", 2.0),
        )
        result = run_backtest(request(
            bars=(
                market_bar("2026-01-02"),
                market_bar("2026-01-03", open_price=100.0),
                market_bar("2026-01-04", open_price=50.0, close_price=55.0),
            ),
            actions=actions,
        ), costs=ZERO_COST)
        final_position = result.positions[-1]
        self.assertEqual(final_position.quantity, 10.0)
        self.assertEqual(final_position.average_cost, 50.0)
        self.assertEqual(result.nav[-1].dividends, 10.0)
        self.assertEqual(result.nav[-1].cash, 510.0)
        self.assertEqual(result.nav[-1].nav, 1_060.0)
        self.assertEqual([item.kind for item in result.corporate_actions], ["split", "dividend"])

    def test_exit_records_realized_pnl(self):
        points = (
            weight_point(),
            weight_point(
                decided_at="2026-01-03T21:00:00Z",
                effective_date="2026-01-04",
                weights={"CASH": 1.0},
            ),
        )
        result = run_backtest(request(
            bars=(
                market_bar("2026-01-02"),
                market_bar("2026-01-03", open_price=100.0),
                market_bar("2026-01-04", open_price=120.0),
            ),
            points=points,
        ), costs=ZERO_COST)
        self.assertEqual([item.side for item in result.orders], ["buy", "sell"])
        self.assertEqual(result.nav[-1].realized_pnl, 100.0)
        self.assertEqual(result.nav[-1].unrealized_pnl, 0.0)
        self.assertEqual(result.nav[-1].nav, 1_100.0)

    def test_missing_held_price_fails_closed(self):
        with self.assertRaisesRegex(BacktestSafetyError, "missing close valuation bar for AAPL"):
            run_backtest(request(
                bars=(
                    market_bar("2026-01-02"),
                    market_bar("2026-01-03"),
                    market_bar("2026-01-04", symbol="MSFT", open_price=200.0),
                ),
                universe=("AAPL", "MSFT"),
            ), costs=ZERO_COST)

    def test_halted_rebalance_fails_without_a_fill(self):
        with self.assertRaisesRegex(BacktestSafetyError, "trading is halted"):
            run_backtest(request(bars=(
                market_bar("2026-01-02"),
                market_bar("2026-01-03", halted=True),
            )), costs=ZERO_COST)

    def test_buy_outside_point_in_time_universe_fails_closed(self):
        with self.assertRaisesRegex(BacktestSafetyError, "outside the effective universe"):
            run_backtest(request(
                bars=(market_bar("2026-01-02"), market_bar("2026-01-03")),
                universe=("MSFT",),
            ), costs=ZERO_COST)

    def test_removed_member_can_still_be_sold_to_cash(self):
        points = (
            weight_point(),
            weight_point(
                decided_at="2026-01-03T21:00:00Z",
                effective_date="2026-01-04",
                weights={"CASH": 1.0},
            ),
        )
        replay = BacktestRequest(
            sessions=("2026-01-02", "2026-01-03", "2026-01-04"),
            bars=(
                market_bar("2026-01-02"),
                market_bar("2026-01-03"),
                market_bar("2026-01-04"),
            ),
            weight_points=points,
            universe_snapshots=(
                UniverseSnapshot("2026-01-01", ("AAPL",), "membership-1"),
                UniverseSnapshot("2026-01-04", ("MSFT",), "membership-2"),
            ),
            config=BacktestConfig(initial_cash=1_000.0),
        )
        result = run_backtest(replay, costs=ZERO_COST)
        self.assertEqual([item.side for item in result.orders], ["buy", "sell"])

    def test_costs_cannot_create_negative_cash(self):
        full_investment = weight_point(weights={"AAPL": 1.0, "CASH": 0.0})
        with self.assertRaisesRegex(BacktestSafetyError, "unavailable cash"):
            run_backtest(request(
                bars=(market_bar("2026-01-02"), market_bar("2026-01-03")),
                points=(full_investment,),
            ), costs=TransactionCostModel(commission_rate=0.01, slippage_bps=0.0))

    def test_current_cohort_is_deterministic_but_always_research_only(self):
        base_bars = (
            market_bar("2026-01-02"),
            market_bar("2026-01-03", close_price=105.0),
        )
        first = run_backtest(request(
            bars=base_bars,
            cohort_mode="current_cohort",
        ), costs=ZERO_COST)
        second = run_backtest(request(
            bars=tuple(reversed(base_bars)),
            cohort_mode="current_cohort",
        ), costs=ZERO_COST)
        self.assertTrue(first.research_only)
        self.assertIn("current_cohort", first.research_reasons[0])
        self.assertEqual(first.input_hash, second.input_hash)
        self.assertEqual(first.artifact_hash, second.artifact_hash)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_point_in_time_membership_is_not_forced_to_research_only(self):
        result = run_backtest(request(bars=(
            market_bar("2026-01-02"),
            market_bar("2026-01-03"),
        )), costs=ZERO_COST)
        self.assertFalse(result.research_only)
        self.assertEqual(result.research_reasons, ())


if __name__ == "__main__":
    unittest.main()
