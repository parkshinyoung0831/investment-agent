"""개인 계좌 규모의 주문 계획: 매도는 나누지 않고, 매수 1건 한도와 전체 한도는 그대로 막는다."""
from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.execution.orders.planning import ExecutionLimits, TargetWeightOrderPlanner, client_order_id

NOW = datetime(2026, 9, 14, 15, tzinfo=timezone.utc)


def _intent(weights: dict[str, float]) -> ExecutionIntent:
    return ExecutionIntent(
        intent_id="intent-size", risk_decision_id="risk-size", proposal_id="proposal-size",
        execution_mode="live", target_weights=weights,
        input_hash=hashlib.sha256(repr(sorted(weights.items())).encode()).hexdigest(),
        not_before=(NOW - timedelta(minutes=1)).isoformat(), expires_at=(NOW + timedelta(minutes=30)).isoformat(),
    )


class OrderSizeTest(unittest.TestCase):
    planner = TargetWeightOrderPlanner(ExecutionLimits(
        min_order_notional=10, max_order_notional=5_000, max_total_notional=20_000, quantity_decimals=0,
    ))

    def plan(self, weights, quantities, prices, portfolio_value):
        return self.planner.plan(
            _intent(weights), portfolio_value=portfolio_value, current_quantities=quantities,
            prices=prices, required_mode="live", now=NOW,
        )

    def test_a_full_exit_is_one_order_even_above_the_per_order_buy_limit(self):
        plans = self.plan({"AAPL": 0.0, "CASH": 1.0}, {"AAPL": 60.0}, {"AAPL": 200.0}, 12_000.0)
        self.assertEqual([(plan.side, plan.quantity) for plan in plans], [("sell", 60.0)])
        self.assertEqual(plans[0].client_order_id,
                         client_order_id(intent_id="intent-size", symbol="AAPL", side="sell", quantity=60.0))

    def test_idempotency_key_is_derived_from_the_plan(self):
        self.assertEqual(
            client_order_id(intent_id="i", symbol="AAPL", side="buy", quantity=5.0),
            "aix_" + hashlib.sha256(b"i|AAPL|buy|5.000000").hexdigest()[:20],
        )

    def test_oversized_buys_still_fail_closed(self):
        with self.assertRaisesRegex(ExecutionSafetyError, "exceeds"):
            self.plan({"AAPL": 0.9, "CASH": 0.1}, {}, {"AAPL": 200.0}, 12_000.0)

    def test_total_notional_limit_still_applies_to_sells(self):
        with self.assertRaisesRegex(ExecutionSafetyError, "total order notional"):
            self.plan({"AAPL": 0.0, "CASH": 1.0}, {"AAPL": 150.0}, {"AAPL": 200.0}, 30_000.0)


if __name__ == "__main__":
    unittest.main()
