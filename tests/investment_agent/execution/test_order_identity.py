"""주문을 쓰기 전에 universe identity를 결박하고 승인 표기를 보존한다."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.execution import db
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.platform.db.sqlite import runtime_connection
from tests.investment_agent.fakes import FakeDatabase


class OrderIdentityTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "runtime.sqlite3"
        env = patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(self.path)})
        env.start()
        self.addCleanup(env.stop)
        now = datetime.now(timezone.utc)
        intent = ExecutionIntent(
            intent_id="intent-1", proposal_id="proposal-1", risk_decision_id="risk-1",
            execution_mode="live", target_weights={"AAPL": .1, "CASH": .9}, input_hash="a" * 64,
            not_before=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1),
        )
        db.ExecutionRepository().save_intent(intent.as_row())

    @staticmethod
    def _row(**overrides) -> dict:
        return {
            "client_order_id": "order-1", "intent_id": "intent-1", "account_seq": 7,
            "ticker": "AAPL", "status": "planned", **overrides,
        }

    @staticmethod
    def _universe_client(identities: list[dict]):
        return FakeDatabase({("universe", "securities"): identities})._client

    def test_write_contains_security_identity_and_approved_ticker(self):
        row = self._row()
        client = self._universe_client([{"security_id": 42, "ticker": "AAPL"}])
        with patch.object(db, "sb", client):
            db.ExecutionRepository().create_planned_order(row)

        with runtime_connection(read_only=True) as connection:
            stored = connection.execute(
                "SELECT payload_json FROM orders WHERE client_order_id=?", ("order-1",)
            ).fetchone()
        payload = json.loads(stored[0])
        self.assertEqual(42, payload["security_id"])
        self.assertEqual("AAPL", payload["ticker"])
        self.assertNotIn("security_id", row)

    def test_missing_or_conflicting_identity_prevents_write(self):
        for identities, supplied in (([], None), ([{"security_id": 42, "ticker": "AAPL"}], 99)):
            with self.subTest(supplied=supplied):
                row = self._row(client_order_id="order-2", security_id=supplied)
                client = self._universe_client(identities)
                with patch.object(db, "sb", client), self.assertRaises(ExecutionSafetyError):
                    db.ExecutionRepository().create_planned_order(row)
                with runtime_connection(read_only=True) as connection:
                    self.assertIsNone(
                        connection.execute(
                            "SELECT 1 FROM orders WHERE client_order_id=?", ("order-2",)
                        ).fetchone()
                    )

    def test_existing_different_security_is_not_reused(self):
        client = self._universe_client([{"security_id": 42, "ticker": "AAPL"}])
        with patch.object(db, "sb", client):
            db.ExecutionRepository().create_planned_order(self._row())

        # 같은 client_order_id를 다시 계획하는데, 이번에는 ticker가 다른 security_id로
        # 풀린다(예: 재배정) — 기존 행을 조용히 덮어써서는 안 된다.
        reassigned_client = self._universe_client([{"security_id": 99, "ticker": "AAPL"}])
        with (
            patch.object(db, "sb", reassigned_client),
            self.assertRaisesRegex(ExecutionSafetyError, "conflicts"),
        ):
            db.ExecutionRepository().create_planned_order(self._row())


if __name__ == "__main__":
    unittest.main()
