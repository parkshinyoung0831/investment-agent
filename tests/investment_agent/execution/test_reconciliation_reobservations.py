"""같은 broker 상태 재관측과 종결 뒤 비용 정정을 보존한다."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.execution.db import ExecutionRepository
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.platform.db.sqlite import runtime_connection


class ReobservationsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        env = patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(Path(temporary.name)/"runtime.sqlite3")})
        env.start()
        self.addCleanup(env.stop)
        self.repo = ExecutionRepository()
        self.now = datetime.now(timezone.utc)

    def test_same_content_later_observation_is_idempotent(self):
        row = dict(snapshot_hash="abc",client_order_id="order",broker_order_id="broker",broker_status="FILLED",filled_quantity="1",average_fill_price="100",commission="1",tax="0",raw_snapshot={},observed_at=self.now.isoformat())
        self.repo.save_broker_order_snapshot(row)
        self.repo.save_broker_order_snapshot({**row,"observed_at":(self.now+timedelta(minutes=1)).isoformat()})
        with runtime_connection(read_only=True) as connection:
            stored = self.repo._record(connection,"broker_order_snapshot","abc")
        self.assertEqual(stored["observed_at"],row["observed_at"])
        with self.assertRaises(ExecutionSafetyError):
            self.repo.save_broker_order_snapshot({**row,"commission":"99"})

    def test_recent_terminal_order_remains_available_for_fee_correction(self):
        intent=ExecutionIntent(intent_id="intent",proposal_id="proposal",risk_decision_id="risk",execution_mode="live",target_weights={"CASH":1.0},input_hash="a"*64,not_before=self.now-timedelta(minutes=1),expires_at=self.now+timedelta(hours=1))
        self.repo.save_intent(intent.as_row())
        row=dict(client_order_id="order",broker_order_id="broker",intent_id="intent",status="filled",account_seq=7,submitted_at=self.now.isoformat(),updated_at=self.now.isoformat())
        with runtime_connection() as connection:
            connection.execute("INSERT INTO orders(client_order_id,broker_order_id,intent_id,status,account_seq,submitted_at,updated_at,payload_json) VALUES(?,?,?,?,?,?,?,?)",("order","broker","intent","filled",7,self.now.isoformat(),self.now.isoformat(),json.dumps(row)))
        self.assertIn("order",[item["client_order_id"] for item in self.repo.reconcilable_orders(account_seq=7)])
        self.assertEqual([],self.repo.reconcilable_orders(account_seq=8))
