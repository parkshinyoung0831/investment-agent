"""실제 SQLite로 동시성·재시도·원장 손실 방지를 검증한다."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.execution.approval.ledger import ApprovalRequest
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.db import ExecutionRepository
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.execution.orders.ledger import OrderAttempt
from investment_agent.platform.db.sqlite import RuntimeMigrationRequired, runtime_connection

ROOT = Path(__file__).resolve().parents[3]
RUNTIME_DDL_ROOT = ROOT / "db/sqlite/runtime/v1"


class RuntimeStorageTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "runtime.sqlite3"
        env = patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(self.path)})
        env.start()
        self.addCleanup(env.stop)
        self.repo = ExecutionRepository()
        self.now = datetime.now(timezone.utc)
        self.intent = ExecutionIntent(
            intent_id="intent-test", proposal_id="proposal-test", risk_decision_id="risk-test",
            execution_mode="live", target_weights={"AAPL": .1, "CASH": .9}, input_hash="a" * 64,
            not_before=self.now - timedelta(minutes=1), expires_at=self.now + timedelta(hours=1),
        )
        self.repo.save_intent(self.intent.as_row())

    def test_runtime_ddl_is_split_by_owner(self):
        self.assertEqual(
            [
                "00_init.sql",
                "10_account.sql",
                "20_decisions.sql",
                "30_execution.sql",
                "40_notifications.sql",
            ],
            [path.name for path in sorted(RUNTIME_DDL_ROOT.glob("*.sql"))],
        )

    def approval(self):
        request = ApprovalRequest.create(
            intent_id=self.intent.intent_id, proposal_id=self.intent.proposal_id,
            risk_decision_id=self.intent.risk_decision_id, execution_mode="live",
            proposal_hash="a" * 64, risk_hash="b" * 64, manifest_hash="c" * 64,
            account_seq=7, allowed_client_order_ids=["order-test"],
            discord_guild_id="1510267057885941840", discord_channel_id="1539250099999999999",
            allowed_approver_user_ids=["1537373837350404146"], requested_at=self.now,
        )
        self.repo.create_approval(request)
        attached = self.repo.attach_approval_message(request.approval_id,
            discord_guild_id=request.discord_guild_id, discord_channel_id=request.discord_channel_id,
            discord_message_id="1539250199999999999")
        return self.repo.decide_approval(request.approval_id, action="approve",
            discord_guild_id=attached.discord_guild_id, discord_channel_id=attached.discord_channel_id,
            discord_message_id=attached.discord_message_id, discord_user_id=attached.allowed_approver_user_ids[0])

    def attempt(self):
        approval = self.approval()
        self.repo.consume_approval(approval.approval_id, manifest_hash=approval.manifest_hash)
        return OrderAttempt.create(client_order_id="order-test", intent_id=self.intent.intent_id,
            approval_id=approval.approval_id, operation="create", request_payload={"quantity": "5"},
            manifest_hash=approval.manifest_hash, account_seq=7)

    def test_concurrent_consumers_only_one_succeeds(self):
        request = self.approval()
        barrier = threading.Barrier(2)
        original = self.repo.load_approval
        def simultaneous_read(key):
            result = original(key)
            barrier.wait(timeout=5)
            return result
        with patch.object(self.repo, "load_approval", side_effect=simultaneous_read):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.repo.consume_approval(request.approval_id,
                    manifest_hash=request.manifest_hash), range(2)))
        self.assertEqual(1, sum(result is not None for result in results))
        self.assertEqual("consumed", self.repo.load_approval(request.approval_id).status)

    def test_concurrent_claims_only_one_succeeds(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.repo.claim_intent(self.intent.intent_id), range(2)))
        self.assertEqual(1, sum(result is not None for result in results))

    def test_later_retry_keeps_original_reservation(self):
        attempt = self.attempt()
        self.assertTrue(self.repo.reserve_order_attempt(attempt).reserved_new)
        result = self.repo.reserve_order_attempt(replace(attempt, reserved_at=attempt.reserved_at + timedelta(seconds=10)))
        self.assertFalse(result.reserved_new)
        self.assertEqual(attempt.reserved_at, result.attempt.reserved_at)

    def test_payload_mutation_cannot_reuse_attempt_hash(self):
        attempt = self.attempt()
        with self.assertRaisesRegex(ExecutionSafetyError, "payload hash"):
            replace(attempt, request_payload={"quantity": "50"})

    def test_attempt_transitions_reject_skips_and_preserve_raw_artifact(self):
        attempt = self.attempt()
        self.repo.reserve_order_attempt(attempt)
        self.assertIsNone(self.repo.append_order_attempt_event(attempt.attempt_id, status="submitted"))
        self.repo.append_order_attempt_event(attempt.attempt_id, status="submitting")
        self.repo.append_order_attempt_event(attempt.attempt_id, status="outcome_unknown", raw_response={"status": "NEW_STATUS"})
        self.assertIsNone(self.repo.append_order_attempt_event(attempt.attempt_id, status="submitting"))
        self.assertEqual(["submitting", "outcome_unknown"], [event.status for event in self.repo.order_attempt_events(attempt.attempt_id)])
        with runtime_connection(read_only=True) as connection:
            detail = json.loads(connection.execute("SELECT detail_json FROM order_events ORDER BY event_id DESC LIMIT 1").fetchone()[0])
        content = Path(detail["raw_artifact_path"]).read_bytes()
        self.assertEqual(detail["raw_sha256"], hashlib.sha256(content).hexdigest())

    def test_fill_replay_cannot_change_quantity(self):
        row = {"broker_fill_id": "fill-test", "broker_order_id": "broker-test", "filled_at": self.now.isoformat(), "quantity": 2, "price": 50}
        self.repo.save_fill(row)
        self.repo.save_fill(row)
        with self.assertRaises(ExecutionSafetyError):
            self.repo.save_fill({**row, "quantity": 3})
        with runtime_connection(read_only=True) as connection:
            quantity, payload = connection.execute("SELECT quantity,payload_json FROM fills").fetchone()
        self.assertEqual(quantity, json.loads(payload)["quantity"])

    def test_nonempty_legacy_ledger_is_not_replaced_with_empty_tables(self):
        legacy = self.path.parent / "legacy.sqlite3"
        with sqlite3.connect(legacy) as connection:
            connection.execute("CREATE TABLE intents(id INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO intents VALUES(1)")
        connection.close()
        with self.assertRaises(RuntimeMigrationRequired):
            with runtime_connection(legacy):
                pass
        with sqlite3.connect(legacy) as connection:
            self.assertEqual([(1,)], connection.execute("SELECT * FROM intents").fetchall())
        connection.close()

    def test_future_intent_cannot_be_claimed(self):
        future = replace(self.intent, intent_id="future", risk_decision_id="future-risk",
            not_before=self.now + timedelta(days=1), expires_at=self.now + timedelta(days=2))
        self.repo.save_intent(future.as_row())
        self.assertIsNone(self.repo.claim_intent(future.intent_id))

    def test_transaction_exception_rolls_back_all_records(self):
        with self.assertRaises(RuntimeError):
            with runtime_connection() as connection:
                connection.execute("DELETE FROM intents")
                raise RuntimeError("injected failure")
        self.assertIsNotNone(self.repo.load_intent(self.intent.intent_id))
