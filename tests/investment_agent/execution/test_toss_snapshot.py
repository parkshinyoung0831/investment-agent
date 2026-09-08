from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.toss_snapshot import capture_toss_account_snapshot


class TossSnapshotTest(unittest.TestCase):
    @mock.patch("investment_agent.execution.orders.toss_snapshot.toss.fetch_buying_power", return_value=500.0)
    @mock.patch(
        "investment_agent.execution.orders.toss_snapshot.toss.fetch_prices",
        return_value=({"AAPL": 100.0}, {"AAPL": "2026-08-22T00:59:30+00:00"}),
    )
    @mock.patch(
        "investment_agent.execution.orders.toss_snapshot.toss.fetch_holdings",
        return_value={"items": [{"marketCountry": "US", "symbol": "AAPL", "quantity": "2"}]},
    )
    @mock.patch("investment_agent.execution.orders.toss_snapshot.toss.fetch_open_orders", return_value=[])
    def test_builds_immutable_usd_snapshot(self, *_mocks):
        snapshot = capture_toss_account_snapshot(
            account_seq=7,
            captured_at=datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(snapshot.account_id, "7")
        self.assertEqual(snapshot.total_value, 700.0)
        self.assertAlmostEqual(snapshot.weights["AAPL"], 2 / 7)

    @mock.patch("investment_agent.execution.orders.toss_snapshot.toss.fetch_open_orders")
    def test_open_order_without_opaque_id_fails_closed(self, open_orders):
        open_orders.return_value = [{"symbol": "AAPL"}]
        with self.assertRaises(ExecutionSafetyError):
            capture_toss_account_snapshot(account_seq=7)

    @mock.patch("investment_agent.execution.orders.toss_snapshot.toss.fetch_buying_power", return_value=500.0)
    @mock.patch(
        "investment_agent.execution.orders.toss_snapshot.toss.fetch_prices",
        return_value=({"AAPL": 100.0}, {"AAPL": "2026-08-21T23:00:00+00:00"}),
    )
    @mock.patch(
        "investment_agent.execution.orders.toss_snapshot.toss.fetch_holdings",
        return_value={"items": [{"marketCountry": "US", "symbol": "AAPL", "quantity": "2"}]},
    )
    @mock.patch("investment_agent.execution.orders.toss_snapshot.toss.fetch_open_orders", return_value=[])
    def test_stale_quote_fails_closed(self, *_mocks):
        with self.assertRaisesRegex(ExecutionSafetyError, "stale"):
            capture_toss_account_snapshot(
                account_seq=7,
                captured_at=datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()

