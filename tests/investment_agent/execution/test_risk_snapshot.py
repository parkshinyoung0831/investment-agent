from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from investment_agent.execution.orders.snapshots import AccountSnapshot, PositionSnapshot
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.risk_snapshot import capture_and_store_risk_snapshot

_NOW = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)


class _Repository:
    def __init__(self):
        self.account = None
        self.positions = None

    def save_account_snapshot(self, row):
        self.account = row
        return 41

    def save_position_snapshots(self, rows):
        self.positions = rows


def _snapshot(account_id: str = "7") -> AccountSnapshot:
    return AccountSnapshot(
        broker="toss",
        account_id=account_id,
        captured_at=_NOW.isoformat(),
        cash_value=100.0,
        positions=(PositionSnapshot("AAPL", 2.0, 50.0, 100.0),),
        open_order_ids=("broker-open-1",),
    )


class RiskSnapshotTest(unittest.TestCase):
    def test_stores_hashed_account_and_positions_without_order_mutation(self):
        repository = _Repository()
        result = capture_and_store_risk_snapshot(
            account_seq=7,
            repository=repository,
            captured_at=_NOW,
            capture=lambda **kwargs: _snapshot(),
        )
        self.assertEqual(result.snapshot_id, 41)
        self.assertEqual(result.equity_usd, 200.0)
        self.assertEqual(
            repository.account["broker_account_hash"],
            hashlib.sha256(b"toss|7").hexdigest(),
        )
        self.assertNotIn("7", repository.account["raw_snapshot"])
        self.assertEqual(repository.positions[0]["ticker"], "AAPL")
        self.assertEqual(repository.positions[0]["weight"], 0.5)

    def test_live_capture_does_not_freeze_clock_before_io(self):
        def capture(**kwargs):
            self.assertIsNone(kwargs["captured_at"])
            return _snapshot()
        with patch("investment_agent.execution.orders.risk_snapshot.datetime") as clock:
            clock.now.return_value = _NOW
            capture_and_store_risk_snapshot(account_seq=7, repository=_Repository(), capture=capture)

    def test_account_mismatch_fails_before_any_write(self):
        repository = _Repository()
        with self.assertRaisesRegex(ExecutionSafetyError, "identity"):
            capture_and_store_risk_snapshot(
                account_seq=7,
                repository=repository,
                captured_at=_NOW,
                capture=lambda **kwargs: _snapshot("8"),
            )
        self.assertIsNone(repository.account)


if __name__ == "__main__":
    unittest.main()
