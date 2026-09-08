from __future__ import annotations

import unittest

from investment_agent.execution.brokers.toss.orders import TossOrderSnapshot
from investment_agent.execution.reconciliation.service import LocalOrder, reconcile_orders


def remote(order_id: str, status: str = "PENDING") -> TossOrderSnapshot:
    return TossOrderSnapshot.from_api({
        "orderId": order_id,
        "symbol": "AAPL",
        "side": "BUY",
        "orderType": "LIMIT",
        "timeInForce": "DAY",
        "status": status,
        "price": "100",
        "quantity": "1",
        "currency": "USD",
        "orderedAt": "2026-08-22T10:00:00+09:00",
        "execution": {
            "filledQuantity": "1" if status == "FILLED" else "0",
            "averageFilledPrice": "99" if status == "FILLED" else None,
            "commission": "0.1" if status == "FILLED" else None,
            "tax": "0",
        },
    })


class ReconciliationTest(unittest.TestCase):
    def test_matches_only_opaque_broker_id_and_surfaces_external_orders(self):
        known = LocalOrder("local-1", "broker-1", "client-1", "submitted")
        unknown = LocalOrder("local-2", None, "client-unknown", "outcome_unknown")
        result = reconcile_orders([known, unknown], [remote("broker-1", "FILLED"), remote("manual")])
        self.assertEqual(result.matched[0][0], known)
        self.assertEqual(result.missing_remote, (unknown,))
        self.assertEqual(result.external_remote[0].order_id, "manual")
        self.assertEqual(result.terminal_remote_ids, ("broker-1",))

    def test_duplicate_broker_ids_fail_closed(self):
        row = LocalOrder("local", "same", "client", "submitted")
        with self.assertRaises(ValueError):
            reconcile_orders([row, row], [])


if __name__ == "__main__":
    unittest.main()

