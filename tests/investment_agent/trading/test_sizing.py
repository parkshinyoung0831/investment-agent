"""비중을 수량으로 바꾸는 자리에서 조용히 틀리는 것들."""
from __future__ import annotations

import unittest

from investment_agent.trading.portfolio.sizing import size_portfolio


class RoundingTest(unittest.TestCase):
    def test_quantities_round_down_not_up(self) -> None:
        """올림하면 현금이 모자라 배치 전체가 흔들린다."""
        result = size_portfolio({"A": 0.10}, {"A": 300.0}, equity=10_000)
        # 0.10 * 10000 / 300 = 3.33 -> 3
        self.assertEqual(3, result.positions[0].target_quantity)

    def test_investment_never_exceeds_the_target(self) -> None:
        result = size_portfolio({"A": 0.10, "B": 0.10}, {"A": 300.0, "B": 700.0}, equity=10_000)
        self.assertLessEqual(result.invested_weight, 0.20)

    def test_an_exact_fit_is_not_reduced(self) -> None:
        result = size_portfolio({"A": 0.30}, {"A": 100.0}, equity=10_000)
        self.assertEqual(30, result.positions[0].target_quantity)


class MissingPriceTest(unittest.TestCase):
    def test_a_missing_price_never_becomes_a_liquidation(self) -> None:
        """가격을 0으로 읽으면 목표 수량이 0이 되어 전량 매도가 된다."""
        result = size_portfolio(
            {"A": 0.10}, {}, equity=10_000, current_quantities={"A": 50}
        )
        self.assertEqual([], result.orders())
        self.assertEqual([{"ticker": "A", "reason": "no_price"}], result.skipped)

    def test_a_zero_price_is_treated_as_missing(self) -> None:
        result = size_portfolio({"A": 0.10}, {"A": 0.0}, equity=10_000)
        self.assertEqual("no_price", result.skipped[0]["reason"])

    def test_a_nan_price_is_treated_as_missing(self) -> None:
        result = size_portfolio({"A": 0.10}, {"A": float("nan")}, equity=10_000)
        self.assertEqual("no_price", result.skipped[0]["reason"])


class MinimumOrderTest(unittest.TestCase):
    def test_a_target_below_one_share_is_recorded_and_skipped(self) -> None:
        """장부에 목표만 남으면 다음 회차가 같은 주문을 또 시도한다."""
        result = size_portfolio({"A": 0.01}, {"A": 5_000.0}, equity=10_000)
        self.assertEqual([], result.orders())
        self.assertEqual("below_one_share", result.skipped[0]["reason"])

    def test_an_existing_holding_is_kept_when_the_target_rounds_to_zero(self) -> None:
        """목표를 0으로 읽어 전량 매도하면 안 된다."""
        result = size_portfolio(
            {"A": 0.01}, {"A": 5_000.0}, equity=10_000, current_quantities={"A": 1}
        )
        self.assertEqual([], result.orders())
        self.assertEqual(1, result.positions[0].target_quantity)

    def test_a_tiny_rebalance_is_not_worth_the_fee(self) -> None:
        result = size_portfolio(
            {"A": 0.101}, {"A": 100.0}, equity=100_000,
            current_quantities={"A": 100}, min_trade_weight=0.01,
        )
        self.assertEqual([], result.orders())
        self.assertEqual("below_min_trade", result.skipped[0]["reason"])

    def test_a_large_enough_rebalance_does_trade(self) -> None:
        result = size_portfolio(
            {"A": 0.20}, {"A": 100.0}, equity=100_000,
            current_quantities={"A": 100}, min_trade_weight=0.01,
        )
        self.assertEqual(100, result.orders()[0].delta_quantity)


class ExitTest(unittest.TestCase):
    def test_a_holding_with_no_target_is_sold(self) -> None:
        """목표에서 빠진 종목이 그대로 남으면 판단과 계좌가 갈라진다."""
        result = size_portfolio(
            {}, {"A": 100.0}, equity=10_000, current_quantities={"A": 10}
        )
        self.assertEqual(-10, result.orders()[0].delta_quantity)

    def test_notional_is_the_traded_amount_not_the_position(self) -> None:
        result = size_portfolio(
            {"A": 0.10}, {"A": 100.0}, equity=10_000, current_quantities={"A": 5}
        )
        self.assertEqual(5, result.orders()[0].delta_quantity)
        self.assertAlmostEqual(500.0, result.orders()[0].notional)


class GuardTest(unittest.TestCase):
    def test_zero_equity_is_refused(self) -> None:
        """0으로 나누면 목표 수량이 무한이 된다."""
        with self.assertRaises(ValueError):
            size_portfolio({"A": 0.10}, {"A": 100.0}, equity=0)

    def test_an_empty_portfolio_produces_no_orders(self) -> None:
        result = size_portfolio({}, {}, equity=10_000)
        self.assertEqual([], result.orders())
        self.assertEqual(0.0, result.invested_weight)


if __name__ == "__main__":
    unittest.main()
