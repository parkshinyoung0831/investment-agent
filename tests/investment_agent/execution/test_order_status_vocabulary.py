"""주문 상태 어휘와 전이표가 한 곳에서 나오고, 대사가 만드는 상태를 모두 안다.

전에는 전이표가 `update_order_execution` 안에만 있었고 `replaced`를 몰랐다. 같은
저장소의 `reconcilable_orders`·대사 worker의 intent 판정·`classify_remote_order`는
그 상태를 아는데 **쓰는 곳 하나만 몰라서**, 브로커가 정정 상태를 주면
`invalid order execution transition`이 대사 패스 전체를 끊었다. 그러면
`unresolved_orders`가 비지 않아 이후 모든 실주문이 막힌다(감사 EX2-03).
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from investment_agent.execution.brokers.toss.orders import TossOrderSnapshot
from investment_agent.execution.orders.ledger import (
    ORDER_STATUSES,
    ORDER_STATUS_TRANSITIONS,
    ORDER_TERMINAL_STATUSES,
)
from investment_agent.execution.reconciliation.worker import classify_remote_order


def _snapshot(status: str, *, quantity="10", filled="0") -> TossOrderSnapshot:
    return TossOrderSnapshot(
        order_id="B1", symbol="US0378331005", side="buy", order_type="limit",
        time_in_force="day", status=status, quantity=Decimal(quantity),
        currency="USD", ordered_at="2026-09-21T13:30:00+00:00", price=Decimal("10"),
        filled_quantity=Decimal(filled), average_filled_price=None,
        commission=None, tax=None, raw={},
    )


class OrderStatusVocabularyTest(unittest.TestCase):
    # 브로커가 실제로 주는 상태 문자열의 계열. 값이 아니라 **분류 결과**를 고정한다.
    REMOTE_STATUSES = (
        "PENDING", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "CANCEL_REQUESTED",
        "CANCEL_REJECTED", "REJECTED", "REPLACED", "REPLACE_REQUESTED",
    )

    def test_every_classified_status_is_a_reachable_transition_target(self):
        reachable = set().union(*ORDER_STATUS_TRANSITIONS.values())
        produced = set()
        for status in self.REMOTE_STATUSES:
            for filled in ("0", "4", "10"):
                produced.add(classify_remote_order(_snapshot(status, filled=filled)))
        self.assertTrue(produced)
        self.assertEqual(produced - reachable, set(), "대사가 만드는 상태가 전이표에 없다")
        self.assertEqual(produced - ORDER_STATUSES, set())

    def test_replaced_is_terminal_and_reachable_from_live_states(self):
        self.assertIn("replaced", ORDER_TERMINAL_STATUSES)
        for origin in ("submitted", "partially_filled", "outcome_unknown", "reconciling"):
            self.assertIn("replaced", ORDER_STATUS_TRANSITIONS[origin], origin)

    def test_transition_targets_are_all_declared_statuses(self):
        for origin, targets in ORDER_STATUS_TRANSITIONS.items():
            self.assertIn(origin, ORDER_STATUSES, origin)
            self.assertEqual(set(targets) - ORDER_STATUSES, set(), origin)

    def test_terminal_states_have_no_outgoing_transitions(self):
        """종결 상태는 불변이다 — 전이표에 출발 상태로 등장하면 안 된다."""
        self.assertEqual(ORDER_TERMINAL_STATUSES & set(ORDER_STATUS_TRANSITIONS), set())


if __name__ == "__main__":
    unittest.main()
