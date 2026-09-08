"""로컬 SQLite 실행 원장의 승인 결속·선점 계약을 검증한다.

Postgres RLS·GRANT·저장 함수는 SQLite에 대응 개념이 없다 — 이 원장은 네트워크에
노출되지 않는 실행 컴퓨터 로컬 파일이라 그 경계 자체가 구조적으로 사라졌다.
남는 계약(조회 인덱스·fail-closed 기본값·compare-and-swap)만 실제 SQLite로 검증한다.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.execution.approval.ledger import ApprovalRequest
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.db import ExecutionRepository
from investment_agent.execution.orders.intents import ExecutionIntent

ROOT = Path(__file__).resolve().parents[3]


class ApprovalSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = (ROOT / "db" / "sqlite" / "runtime" / "v1" / "30_execution.sql").read_text(encoding="utf-8")

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

    def approval(self) -> ApprovalRequest:
        request = ApprovalRequest.create(
            intent_id=self.intent.intent_id, proposal_id=self.intent.proposal_id,
            risk_decision_id=self.intent.risk_decision_id, execution_mode="live",
            proposal_hash="a" * 64, risk_hash="b" * 64, manifest_hash="c" * 64,
            account_seq=7, allowed_client_order_ids=["order-test"],
            discord_guild_id="1510267057885941840", discord_channel_id="1539250099999999999",
            allowed_approver_user_ids=["1537373837350404146"], requested_at=self.now,
        )
        self.repo.create_approval(request)
        return self.repo.attach_approval_message(
            request.approval_id, discord_guild_id=request.discord_guild_id,
            discord_channel_id=request.discord_channel_id, discord_message_id="1539250199999999999",
        )

    def test_lookup_indexes_exist(self) -> None:
        for index in (
            "intents_pending_idx", "approvals_status_expiry_idx",
            "order_events_attempt_idx", "orders_reconciliation_idx",
        ):
            self.assertIn(index, self.sql)

    def test_missing_control_state_fails_closed_rather_than_defaulting_open(self) -> None:
        """새 설치는 execution_control 행을 자동으로 채우지 않는다.

        Postgres 시절에는 스키마 적용이 kill_switch_on=true인 기본 행을 심었지만,
        지금은 그 대신 행이 없으면 그냥 막는다 — 사람이 ``harness_switch``로 명시적으로
        켜기 전까지는 상태를 읽지 못해 주문 경로 전체가 멈춘다.
        """
        with self.assertRaises(ExecutionSafetyError):
            self.repo.load_control_state()

    def test_decide_approval_is_compare_and_swap(self) -> None:
        attached = self.approval()
        approved = self.repo.decide_approval(
            attached.approval_id, action="approve",
            discord_guild_id=attached.discord_guild_id, discord_channel_id=attached.discord_channel_id,
            discord_message_id=attached.discord_message_id, discord_user_id=attached.allowed_approver_user_ids[0],
        )
        self.assertIsNotNone(approved)
        self.assertEqual("approved", approved.status)
        repeat = self.repo.decide_approval(
            attached.approval_id, action="reject",
            discord_guild_id=attached.discord_guild_id, discord_channel_id=attached.discord_channel_id,
            discord_message_id=attached.discord_message_id, discord_user_id=attached.allowed_approver_user_ids[0],
        )
        self.assertIsNone(repeat, "이미 결정된 승인은 다시 결정할 수 없어야 한다")
        self.assertEqual("approved", self.repo.load_approval(attached.approval_id).status)

    def test_consume_approval_is_compare_and_swap(self) -> None:
        attached = self.approval()
        self.repo.decide_approval(
            attached.approval_id, action="approve",
            discord_guild_id=attached.discord_guild_id, discord_channel_id=attached.discord_channel_id,
            discord_message_id=attached.discord_message_id, discord_user_id=attached.allowed_approver_user_ids[0],
        )
        approved = self.repo.load_approval(attached.approval_id)
        first = self.repo.consume_approval(approved.approval_id, manifest_hash=approved.manifest_hash)
        self.assertIsNotNone(first)
        second = self.repo.consume_approval(approved.approval_id, manifest_hash=approved.manifest_hash)
        self.assertIsNone(second, "이미 소비된 승인은 다시 소비할 수 없어야 한다")

    def test_no_broker_submission_is_added_to_approval_modules(self) -> None:
        forbidden = ("submit_order", "/api/v1/orders", "requests.post")
        for path in Path("src/investment_agent/execution").glob("approval*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, path.as_posix())


if __name__ == "__main__":
    unittest.main()
