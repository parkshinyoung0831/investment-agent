from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from investment_agent.execution.approval.ledger import ApprovalRequest
from investment_agent.execution.approval.status import publish_reconciliation_statuses
from investment_agent.execution.reconciliation.worker import ReconciliationCardUpdate

NOW = datetime(2026, 8, 24, 15, 5, tzinfo=timezone.utc)
APPROVAL_ID = "approval_" + "a" * 32
GUILD_ID = "1510267057885941840"
CHANNEL_ID = "1540628419094642699"
MESSAGE_ID = "1540628999999999999"
USER_ID = "1537373837350404146"


def consumed_approval(**changes) -> ApprovalRequest:
    pending = ApprovalRequest.create(
        intent_id="intent-1",
        proposal_id="proposal-1",
        risk_decision_id="risk-1",
        execution_mode="live",
        proposal_hash="a" * 64,
        risk_hash="b" * 64,
        manifest_hash="c" * 64,
        account_seq=7,
        allowed_client_order_ids=("client-1",),
        discord_guild_id=GUILD_ID,
        discord_channel_id=CHANNEL_ID,
        allowed_approver_user_ids=(USER_ID,),
        requested_at=NOW - timedelta(minutes=2),
        latest_expiry=NOW + timedelta(minutes=10),
    )
    value = replace(
        pending,
        approval_id=APPROVAL_ID,
        status="consumed",
        decision="approved",
        discord_message_id=MESSAGE_ID,
        decided_at=(NOW - timedelta(minutes=1)).isoformat(),
        decided_by_user_id=USER_ID,
        consumed_at=NOW.isoformat(),
    )
    return replace(value, **changes)


class FakeRepository:
    def __init__(self, approval: ApprovalRequest | None):
        self.approval = approval

    def load_approval(self, approval_id: str):
        if self.approval and approval_id == self.approval.approval_id:
            return self.approval
        return None


class FakeClient:
    instances = []
    fail = False

    def __init__(self, *, bot_token: str, guild_id: str):
        self.guild_id = guild_id
        self.calls = []
        self.instances.append(self)

    def set_status_text(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise TimeoutError("Discord timeout")


class ApprovalStatusTest(unittest.TestCase):
    def setUp(self):
        FakeClient.instances = []
        FakeClient.fail = False
        self.update = ReconciliationCardUpdate(
            approval_id=APPROVAL_ID,
            intent_id="intent-1",
            status="filled",
        )

    def publish(self, approval=None, **kwargs):
        return publish_reconciliation_statuses(
            repository=FakeRepository(approval or consumed_approval()),
            updates=(self.update,),
            account_seq=7,
            bot_token=kwargs.get("bot_token", "test-token"),
            expected_guild_id=kwargs.get("guild_id", GUILD_ID),
            expected_channel_id=kwargs.get("channel_id", CHANNEL_ID),
            client_factory=FakeClient,
        )

    def test_exact_consumed_approval_updates_only_its_bound_message(self):
        result = self.publish()
        self.assertEqual((result.sent, result.failed, result.skipped), (1, 0, 0))
        self.assertEqual(len(FakeClient.instances), 1)
        call = FakeClient.instances[0].calls[0]
        self.assertEqual(call["channel_id"], CHANNEL_ID)
        self.assertEqual(call["message_id"], MESSAGE_ID)
        self.assertIn("전량 체결", call["content"])

    def test_wrong_channel_account_or_unconsumed_approval_never_sends(self):
        cases = (
            (consumed_approval(discord_channel_id="1540628419094642698"), {}),
            (consumed_approval(account_seq=8), {}),
            (
                consumed_approval(
                    status="approved",
                    consumed_at=None,
                ),
                {},
            ),
        )
        for approval, options in cases:
            with self.subTest(approval=approval):
                FakeClient.instances = []
                result = self.publish(approval, **options)
                self.assertEqual(result.failed, 1)
                self.assertEqual(FakeClient.instances, [])

    def test_missing_bot_configuration_is_a_noop(self):
        result = self.publish(bot_token="")
        self.assertEqual((result.sent, result.failed, result.skipped), (0, 0, 1))
        self.assertEqual(FakeClient.instances, [])

    def test_discord_failure_does_not_escape_or_change_the_ledger(self):
        FakeClient.fail = True
        approval = consumed_approval()
        result = self.publish(approval)
        self.assertEqual((result.sent, result.failed), (0, 1))
        self.assertEqual(approval.status, "consumed")


if __name__ == "__main__":
    unittest.main()
