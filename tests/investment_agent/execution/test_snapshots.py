from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from investment_agent.platform.serialization import ContractError
from investment_agent.execution.orders.snapshots import AccountSnapshot, PositionSnapshot


def position(ticker: str, value: float) -> PositionSnapshot:
    return PositionSnapshot(
        ticker=ticker,
        quantity=value / 10.0,
        market_price=10.0,
        market_value=value,
    )


class AccountSnapshotTest(unittest.TestCase):
    def test_snapshot_is_immutable_and_content_addressed(self):
        first = AccountSnapshot(
            broker="TOSS",
            account_id="7",
            captured_at="2026-08-22T12:00:00+00:00",
            cash_value=40.0,
            positions=(position("MSFT", 20.0), position("aapl", 40.0)),
            open_order_ids=("order-2", "order-1"),
        )
        reordered = AccountSnapshot(
            broker="toss",
            account_id="7",
            captured_at="2026-08-22T12:00:00Z",
            cash_value=40.0,
            positions=(position("AAPL", 40.0), position("MSFT", 20.0)),
            open_order_ids=("order-1", "order-2"),
        )
        self.assertEqual(first.snapshot_id, reordered.snapshot_id)
        self.assertEqual(first.positions[0].ticker, "AAPL")
        self.assertAlmostEqual(sum(first.weights.values()), 1.0)
        self.assertAlmostEqual(first.weights["AAPL"], 0.4)
        with self.assertRaises(FrozenInstanceError):
            first.cash_value = 1.0  # type: ignore[misc]

    def test_rejects_duplicate_and_unpriced_positions(self):
        with self.assertRaisesRegex(ContractError, "duplicate"):
            AccountSnapshot(
                broker="toss",
                account_id="7",
                captured_at="2026-08-22T12:00:00+00:00",
                cash_value=1.0,
                positions=(position("AAPL", 10.0), position("aapl", 20.0)),
            )
        with self.assertRaisesRegex(ContractError, "fresh positive price"):
            PositionSnapshot(ticker="AAPL", quantity=1, market_price=0, market_value=10)

    def test_account_and_freshness_are_fail_closed(self):
        snapshot = AccountSnapshot(
            broker="toss",
            account_id="7",
            captured_at="2026-08-22T12:00:00+00:00",
            cash_value=100.0,
        )
        snapshot.assert_usable(
            expected_account_id="7",
            as_of_at="2026-08-22T12:04:59+00:00",
            max_age_seconds=300,
        )
        with self.assertRaisesRegex(ContractError, "account does not match"):
            snapshot.assert_usable(
                expected_account_id="8",
                as_of_at="2026-08-22T12:01:00+00:00",
                max_age_seconds=300,
            )
        with self.assertRaisesRegex(ContractError, "stale"):
            snapshot.assert_usable(
                expected_account_id="7",
                as_of_at="2026-08-22T12:05:01+00:00",
                max_age_seconds=300,
            )
        with self.assertRaisesRegex(ContractError, "future"):
            snapshot.assert_usable(
                expected_account_id="7",
                as_of_at="2026-08-22T11:59:59+00:00",
                max_age_seconds=300,
            )


if __name__ == "__main__":
    unittest.main()
