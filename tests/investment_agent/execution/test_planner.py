from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timezone

from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.planning import ExecutionLimits, TargetWeightOrderPlanner


def intent(*, expires_at: str = "2026-08-21T13:00:00+00:00") -> ExecutionIntent:
    return ExecutionIntent(
        intent_id="intent-1", risk_decision_id="risk-1", proposal_id="proposal-1",
        execution_mode="paper", target_weights={"AAPL": 0.1, "MSFT": 0.1, "CASH": 0.8},
        input_hash=hashlib.sha256(b"input").hexdigest(),
        not_before="2026-08-21T11:00:00+00:00", expires_at=expires_at,
    )


class OrderPlannerTest(unittest.TestCase):
    def test_sells_are_ordered_before_buys(self):
        planner = TargetWeightOrderPlanner(ExecutionLimits(
            min_order_notional=1, max_order_notional=10_000, max_total_notional=20_000,
        ))
        plans = planner.plan(
            intent(), portfolio_value=10_000,
            current_quantities={"AAPL": 20.0, "MSFT": 0.0},
            prices={"AAPL": 100.0, "MSFT": 100.0},
            now=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        )
        self.assertEqual([plan.side for plan in plans], ["sell", "buy"])

    def test_expired_intent_fails_closed(self):
        planner = TargetWeightOrderPlanner()
        with self.assertRaises(ExecutionSafetyError):
            planner.plan(
                intent(expires_at="2026-08-21T11:30:00+00:00"),
                portfolio_value=1000, current_quantities={},
                prices={"AAPL": 100, "MSFT": 100},
                now=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
            )

    def test_order_notional_limit_rejects_instead_of_clipping(self):
        planner = TargetWeightOrderPlanner(ExecutionLimits(max_order_notional=100))
        with self.assertRaises(ExecutionSafetyError):
            planner.plan(
                intent(), portfolio_value=10_000, current_quantities={},
                prices={"AAPL": 100, "MSFT": 100},
                now=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
            )

    def test_non_member_buy_is_blocked_but_existing_position_can_be_sold(self):
        planner = TargetWeightOrderPlanner(ExecutionLimits(
            min_order_notional=1, max_order_notional=10_000, max_total_notional=20_000,
        ))
        with self.assertRaises(ExecutionSafetyError):
            planner.plan(
                intent(), portfolio_value=10_000, current_quantities={},
                prices={"AAPL": 100, "MSFT": 100}, eligible_buy_symbols={"MSFT"},
                now=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
            )

        sell_only = intent()
        plans = planner.plan(
            sell_only, portfolio_value=1_000,
            current_quantities={"AAPL": 20, "MSFT": 1},
            prices={"AAPL": 100, "MSFT": 100}, eligible_buy_symbols={"MSFT"},
            now=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(plans[0].symbol, "AAPL")
        self.assertEqual(plans[0].side, "sell")

    def test_quantity_is_floored_and_limits_use_the_executable_quantity(self):
        planner = TargetWeightOrderPlanner(ExecutionLimits(
            min_order_notional=1,
            max_order_notional=100,
            max_total_notional=200,
            quantity_decimals=0,
        ))
        small = ExecutionIntent(
            intent_id="intent-floor", risk_decision_id="risk-floor",
            proposal_id="proposal-floor", execution_mode="paper",
            target_weights={"AAPL": 0.099, "CASH": 0.901},
            input_hash=hashlib.sha256(b"floor").hexdigest(),
            not_before="2026-08-21T11:00:00+00:00",
            expires_at="2026-08-21T13:00:00+00:00",
        )
        plans = planner.plan(
            small,
            portfolio_value=1_000,
            current_quantities={},
            prices={"AAPL": 10},
            now=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(plans[0].quantity, 9)
        self.assertEqual(plans[0].notional, 90)

    def test_holding_omitted_from_targets_is_preserved(self):
        planner = TargetWeightOrderPlanner(ExecutionLimits(
            min_order_notional=1,
            max_order_notional=10_000,
            max_total_notional=20_000,
        ))
        plans = planner.plan(
            intent(),
            portfolio_value=10_000,
            current_quantities={"AAPL": 10, "MSFT": 10, "NVDA": 5},
            prices={"AAPL": 100, "MSFT": 100},
            now=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        )
        self.assertNotIn("NVDA", {plan.symbol for plan in plans})


if __name__ == "__main__":
    unittest.main()
