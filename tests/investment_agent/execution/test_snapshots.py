from __future__ import annotations

import subprocess
import sys
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
    def test_safety_import_keeps_public_contracts_available(self):
        """안전 게이트 초기화가 계약의 주문 타입 재노출을 순환시키지 않는다."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from investment_agent.execution.safety.control import ExecutionSafetyError; "
                    "from investment_agent.execution.contracts import AccountSnapshot, ExecutionLimits"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_public_contract_re_exports_trading_inputs(self):
        """Trading은 orders 내부가 아니라 고정된 execution 계약만 본다."""
        from investment_agent.execution.contracts import AccountSnapshot as PublicAccountSnapshot
        from investment_agent.execution.contracts import ExecutionLimits
        from investment_agent.execution.orders.planning import ExecutionLimits as PlannerExecutionLimits

        self.assertIs(PublicAccountSnapshot, AccountSnapshot)
        self.assertIs(ExecutionLimits, PlannerExecutionLimits)

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
