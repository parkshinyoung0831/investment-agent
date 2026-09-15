"""자금 확보 매도가 끝난 System 목표만 한 번 더 따라갈 수 있다."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.db import (
    RECORD_SYSTEM_TARGET_EXECUTION,
    ExecutionRepository,
    funding_followup_allowed,
)
from investment_agent.platform.db.sqlite import runtime_connection

NOW = datetime.now(timezone.utc)


def _intent_row(intent_id: str, *, status: str = "completed") -> dict:
    return {
        "intent_id": intent_id, "risk_decision_id": f"risk-{intent_id}", "proposal_id": f"proposal-{intent_id}",
        "execution_mode": "live", "target_weights": {"AAPL": 0.0, "CASH": 1.0},
        "input_hash": hashlib.sha256(intent_id.encode()).hexdigest(),
        "not_before": (NOW - timedelta(minutes=5)).isoformat(),
        "expires_at": (NOW + timedelta(minutes=30)).isoformat(), "status": status,
    }


class FundingFollowupTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        env = patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(Path(temporary.name) / "runtime.sqlite3")})
        env.start()
        self.addCleanup(env.stop)
        self.repository = ExecutionRepository()

    def seed(self, *, phase: str = "funding_sells", intent_status: str = "completed",
             order_status: str = "filled", followups: int = 0) -> None:
        with runtime_connection() as connection:
            row = _intent_row("intent-1", status=intent_status)
            connection.execute(
                "INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?)",
                (row["intent_id"], row["proposal_id"], row["risk_decision_id"], "live", intent_status,
                 row["not_before"], row["expires_at"], json.dumps(row), NOW.isoformat(), NOW.isoformat()),
            )
            connection.execute(
                "INSERT INTO order_manifests VALUES(?,?,?,?,?)",
                ("m" * 64, "intent-1", 7, json.dumps({"funding_phase": phase}), NOW.isoformat()),
            )
            order = {"client_order_id": "aix_1", "intent_id": "intent-1", "status": order_status, "side": "sell"}
            connection.execute(
                "INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)",
                ("aix_1", "broker-1", "intent-1", order_status, 7, NOW.isoformat(), NOW.isoformat(), json.dumps(order)),
            )
            claim = {"intent_id": "intent-1"}
            if followups:
                claim["funding_followups"] = followups
            ExecutionRepository._save_record(connection, RECORD_SYSTEM_TARGET_EXECUTION, "target-1", claim)

    def allowed(self) -> bool:
        with runtime_connection(read_only=True) as connection:
            claim = ExecutionRepository._record(connection, RECORD_SYSTEM_TARGET_EXECUTION, "target-1")
            return funding_followup_allowed(connection, claim)

    def test_finished_funding_sells_open_exactly_one_followup(self):
        self.seed()
        self.assertTrue(self.allowed())
        # 승인을 이미 물었더라도 매도만 끝난 목표는 다시 따라갈 수 있다.
        self.assertFalse(self.repository.is_system_target_followed("target-1"))

    def test_each_unsettled_or_non_funding_state_keeps_the_target_closed(self):
        for overrides in (
            {"phase": "full"},
            {"intent_status": "executing"},
            {"order_status": "submitted"},
            {"order_status": "partially_filled"},
            {"followups": 1},
        ):
            with self.subTest(overrides=overrides):
                self.setUp()
                self.seed(**overrides)
                self.assertFalse(self.allowed())

    def test_followup_intent_is_accepted_once_and_then_the_target_closes(self):
        self.seed()
        with patch.object(self.repository, "_decision_row", return_value={"metadata": {"system_target_id": "target-1"}}):
            self.repository.save_intent(_intent_row("intent-2", status="approved"))
            with runtime_connection(read_only=True) as connection:
                claim = ExecutionRepository._record(connection, RECORD_SYSTEM_TARGET_EXECUTION, "target-1")
            self.assertEqual(claim["intent_id"], "intent-2")
            self.assertEqual(claim["funding_followups"], 1)
            self.assertEqual(claim["previous_intent_ids"], ["intent-1"])
            with self.assertRaisesRegex(ExecutionSafetyError, "active execution"):
                self.repository.save_intent(_intent_row("intent-3", status="approved"))


class SupersessionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        env = patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(Path(temporary.name) / "runtime.sqlite3")})
        env.start()
        self.addCleanup(env.stop)
        self.repository = ExecutionRepository()

    def status(self, intent_id: str) -> tuple[str, dict]:
        with runtime_connection(read_only=True) as connection:
            row = connection.execute("SELECT status,payload_json FROM intents WHERE intent_id=?", (intent_id,)).fetchone()
        return row[0], json.loads(row[1])

    def test_newer_live_judgment_cancels_older_pending_approval(self):
        with patch.object(self.repository, "_decision_row", return_value=None):
            self.repository.save_intent(_intent_row("old", status="approved"))
            self.repository.save_intent(_intent_row("new", status="approved"))
        status, payload = self.status("old")
        self.assertEqual(status, "cancelled")
        self.assertEqual(payload["superseded_by"], "new")
        self.assertEqual(self.status("new")[0], "approved")

    def test_intent_with_orders_is_never_superseded(self):
        with patch.object(self.repository, "_decision_row", return_value=None):
            self.repository.save_intent(_intent_row("sent", status="approved"))
            with runtime_connection() as connection:
                connection.execute(
                    "INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)",
                    ("aix_s", "b", "sent", "submitted", 7, NOW.isoformat(), NOW.isoformat(), "{}"),
                )
            self.repository.save_intent(_intent_row("new", status="approved"))
        self.assertEqual(self.status("sent")[0], "approved")

    def test_retrying_the_same_intent_does_not_cancel_anything(self):
        with patch.object(self.repository, "_decision_row", return_value=None):
            self.repository.save_intent(_intent_row("one", status="approved"))
            self.repository.save_intent(_intent_row("one", status="approved"))
        self.assertEqual(self.status("one")[0], "approved")


if __name__ == "__main__":
    unittest.main()
