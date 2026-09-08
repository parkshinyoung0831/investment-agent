from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.execution.approval.ledger import ApprovalRequest
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.db import ExecutionRepository, _same_planned_value
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.execution.orders.ledger import OrderAttempt
from investment_agent.platform.db.sqlite import runtime_connection
from tests.investment_agent.fakes import FakeDatabase

_NOW = datetime(2026, 8, 22, 7, tzinfo=timezone.utc)


def _attempt(*, approval_id: str = "approval_0123456789abcdef0123456789abcdef") -> OrderAttempt:
    return OrderAttempt.create(
        client_order_id="live-aapl-buy", intent_id="intent-live",
        approval_id=approval_id,
        operation="create", request_payload={"symbol": "AAPL", "quantity": "5"},
        manifest_hash="c" * 64, account_seq=7, reserved_at=_NOW,
    )


class ExecutionAttemptRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "runtime.sqlite3"
        env = patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(self.path)})
        env.start()
        self.addCleanup(env.stop)
        self.repo = ExecutionRepository()

    def _consumed_approval(self) -> ApprovalRequest:
        """예약이 통과하려면 approval이 consumed 상태여야 한다(execution/db.py 참고).

        decide_approval/attach_approval_message는 만료를 실제 현재 시각과 비교하므로
        ``_NOW``(고정된 과거 시각)가 아니라 실제 시각을 requested_at으로 쓴다.
        """
        now = datetime.now(timezone.utc)
        intent = ExecutionIntent(
            intent_id="intent-live", proposal_id="proposal-live", risk_decision_id="risk-live",
            execution_mode="live", target_weights={"AAPL": .1, "CASH": .9}, input_hash="a" * 64,
            not_before=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1),
        )
        self.repo.save_intent(intent.as_row())
        request = ApprovalRequest.create(
            intent_id=intent.intent_id, proposal_id=intent.proposal_id,
            risk_decision_id=intent.risk_decision_id, execution_mode="live",
            proposal_hash="a" * 64, risk_hash="b" * 64, manifest_hash="c" * 64,
            account_seq=7, allowed_client_order_ids=["live-aapl-buy"],
            discord_guild_id="1510267057885941840", discord_channel_id="1539250099999999999",
            allowed_approver_user_ids=["1537373837350404146"], requested_at=now,
        )
        self.repo.create_approval(request)
        attached = self.repo.attach_approval_message(
            request.approval_id, discord_guild_id=request.discord_guild_id,
            discord_channel_id=request.discord_channel_id, discord_message_id="1539250199999999999",
        )
        approved = self.repo.decide_approval(
            attached.approval_id, action="approve",
            discord_guild_id=attached.discord_guild_id, discord_channel_id=attached.discord_channel_id,
            discord_message_id=attached.discord_message_id, discord_user_id=attached.allowed_approver_user_ids[0],
        )
        self.repo.consume_approval(approved.approval_id, manifest_hash=approved.manifest_hash)
        return approved

    def test_planned_numeric_identity_ignores_json_decimal_formatting_only(self):
        self.assertTrue(_same_planned_value("quantity", "5.000000", 5.0))
        self.assertTrue(_same_planned_value("notional", "1000.00", 1000))
        self.assertFalse(_same_planned_value("quantity", "5.000001", 5.0))
        self.assertFalse(_same_planned_value("symbol", "AAPL", "MSFT"))

    def test_existing_exact_reservation_is_returned_but_not_marked_new(self):
        approval = self._consumed_approval()
        attempt = _attempt(approval_id=approval.approval_id)
        first = self.repo.reserve_order_attempt(attempt)
        self.assertTrue(first.reserved_new)

        result = self.repo.reserve_order_attempt(attempt)
        self.assertIsNotNone(result)
        self.assertFalse(result.reserved_new)
        with self.assertRaisesRegex(ExecutionSafetyError, "reconcile"):
            result.require_new()

    def test_mismatch_or_invalid_transition_returns_none(self):
        """소비되지 않은(또는 없는) 승인으로는 예약이 안 되고, 없는 attempt에는
        사건을 못 붙인다 — 둘 다 아무것도 쓰지 않고 조용히 None을 준다."""
        reserved = self.repo.reserve_order_attempt(_attempt())
        event = self.repo.append_order_attempt_event(
            _attempt().attempt_id,
            status="submitted",
            raw_status="UNKNOWN_NEW_TOSS_STATUS",
            raw_response={"status": "UNKNOWN_NEW_TOSS_STATUS"},
            occurred_at=_NOW,
        )
        self.assertIsNone(reserved)
        self.assertIsNone(event)
        with runtime_connection(read_only=True) as connection:
            self.assertIsNone(connection.execute("SELECT 1 FROM order_attempts LIMIT 1").fetchone())
            self.assertIsNone(connection.execute("SELECT 1 FROM order_events LIMIT 1").fetchone())

    def test_position_snapshot_resolves_ticker_to_universe_security_id(self):
        fake = FakeDatabase({("universe", "securities"): [{"security_id": 17, "ticker": "AAPL"}]})
        with patch("investment_agent.execution.db.sb", fake._client):
            self.repo.save_position_snapshots([{
                "account_snapshot_id": 41,
                "ticker": "aapl",
                "quantity": 2.0,
                "market_price": 50.0,
                "market_value": 100.0,
                "weight": 0.5,
            }])

        with runtime_connection(read_only=True) as connection:
            row = connection.execute(
                "SELECT payload_json FROM runtime_records WHERE record_type='position_snapshot'"
            ).fetchone()
        payload = json.loads(row[0])
        self.assertEqual(payload["security_id"], 17)
        self.assertNotIn("ticker", payload)


if __name__ == "__main__":
    unittest.main()
