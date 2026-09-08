from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.ledger import OrderAttempt

_NOW = datetime(2026, 8, 22, 7, tzinfo=timezone.utc)


def _attempt(payload=None) -> OrderAttempt:
    return OrderAttempt.create(
        client_order_id="live-aapl-buy",
        intent_id="intent-live",
        approval_id="approval_0123456789abcdef0123456789abcdef",
        operation="create",
        request_payload=payload or {"symbol": "AAPL", "quantity": "5"},
        manifest_hash="c" * 64,
        account_seq=7,
        reserved_at=_NOW,
    )


class OrderAttemptContractTest(unittest.TestCase):
    def test_attempt_identity_is_deterministic_and_payload_bound(self):
        first = _attempt()
        second = _attempt()
        changed = _attempt({"symbol": "AAPL", "quantity": "6"})
        self.assertEqual(first.attempt_id, second.attempt_id)
        self.assertEqual(first.payload_hash, second.payload_hash)
        self.assertNotEqual(first.attempt_id, changed.attempt_id)
        with self.assertRaisesRegex(ExecutionSafetyError, "does not match"):
            replace(first, payload_hash="d" * 64)

    def test_invalid_operation_or_naive_time_fails_closed(self):
        with self.assertRaisesRegex(ExecutionSafetyError, "operation"):
            OrderAttempt.create(
                client_order_id="x", intent_id="i", approval_id="a",
                operation="retry", request_payload={}, manifest_hash="c" * 64,
                account_seq=7, reserved_at=_NOW,
            )
        with self.assertRaisesRegex(ExecutionSafetyError, "timezone"):
            OrderAttempt.create(
                client_order_id="x", intent_id="i", approval_id="a",
                operation="create", request_payload={}, manifest_hash="c" * 64,
                account_seq=7, reserved_at=datetime(2026, 8, 22, 7),
            )


class OrderAttemptSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = Path("db/sqlite/runtime/v1/30_execution.sql").read_text(encoding="utf-8")

    def test_attempt_and_event_tables_have_local_immutable_identities(self):
        for table in ("order_attempts", "order_events"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", self.sql)
        self.assertIn("attempt_id TEXT PRIMARY KEY", self.sql)
        self.assertIn("event_id INTEGER PRIMARY KEY", self.sql)
        self.assertIn("REFERENCES order_attempts(attempt_id)", self.sql)

    def test_reservation_contract_requires_consumed_approval_and_exact_plan(self):
        source = Path("src/investment_agent/execution/db.py").read_text(encoding="utf-8")
        for clause in (
            'approval[0] != "consumed"',
            "attempt.client_order_id",
            "attempt.manifest_hash",
            "reserved_new=False",
        ):
            self.assertIn(clause, source)

    def test_unknown_and_reconciliation_are_immutable_events(self):
        source = Path("src/investment_agent/execution/orders/ledger.py").read_text(encoding="utf-8")
        self.assertIn("outcome_unknown", source)
        self.assertIn("reconciling", source)
        self.assertIn("reconciled_submitted", source)
        self.assertIn("replaces_client_order_id", source)
        self.assertIn("raw_artifact_path", self.sql)


if __name__ == "__main__":
    unittest.main()
