from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.execution.approval.ledger import ApprovalRequest, issue_live_execution_permit
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.toss_manual import TossManualHandoff, TossManualSnapshot, TossManualTicket

_NOW = datetime(2026, 8, 22, 7, tzinfo=timezone.utc)
_GUILD = "1510267057885941840"
_CHANNEL = "1539250099999999999"
_MESSAGE = "1539250199999999999"
_USER = "1537373837350404146"


def _intent(execution_mode: str = "live") -> ExecutionIntent:
    return ExecutionIntent(
        intent_id="intent-live-bridge",
        risk_decision_id="risk-live",
        proposal_id="proposal-live",
        execution_mode=execution_mode,
        target_weights={"AAPL": 0.1, "CASH": 0.9},
        input_hash=hashlib.sha256(b"live-intent").hexdigest(),
        not_before=(_NOW - timedelta(minutes=1)).isoformat(),
        expires_at=(_NOW + timedelta(minutes=30)).isoformat(),
    )


def _handoff(account_seq: int = 7) -> TossManualHandoff:
    handoff = TossManualHandoff(
        intent_id="intent-live-bridge",
        account_seq=account_seq,
        contract_version="toss-manual-v1",
        snapshot=TossManualSnapshot(
            captured_at=_NOW.isoformat(), currency="USD", portfolio_value=10_000,
            cash_buying_power=10_000, current_quantities={}, prices={"AAPL": 200},
            price_timestamps={"AAPL": _NOW.isoformat()},
        ),
        tickets=(TossManualTicket(
            intent_id="intent-live-bridge", client_order_id="live-aapl-buy",
            expires_at=(_NOW + timedelta(minutes=30)).isoformat(), symbol="AAPL",
            side="buy", current_quantity=0, target_weight=0.1, target_quantity=5,
            order_quantity=5, reference_price=200, price_timestamp=_NOW.isoformat(),
            estimated_notional=1_000,
        ),),
        manifest_hash="0" * 64,
    )
    return replace(handoff, manifest_hash=handoff.recomputed_manifest_hash())


def _consumed(execution_mode: str = "live", account_seq: int = 7) -> ApprovalRequest:
    handoff = _handoff(account_seq)
    pending = ApprovalRequest.create(
        intent_id="intent-live-bridge", proposal_id="proposal-live",
        risk_decision_id="risk-live", execution_mode=execution_mode, proposal_hash="a" * 64,
        risk_hash="b" * 64, manifest_hash=handoff.manifest_hash, account_seq=account_seq,
        allowed_client_order_ids=("live-aapl-buy",), discord_guild_id=_GUILD,
        discord_channel_id=_CHANNEL, allowed_approver_user_ids=(_USER,),
        requested_at=_NOW - timedelta(minutes=1), ttl=timedelta(minutes=15),
    )
    return replace(
        pending,
        status="consumed",
        decision="approved",
        discord_message_id=_MESSAGE,
        decided_at=(_NOW - timedelta(seconds=10)).isoformat(),
        decided_by_user_id=_USER,
        consumed_at=(_NOW - timedelta(seconds=5)).isoformat(),
    )


def _issue(*, execution_mode: str = "live", account_seq: int = 7, source_account_seq: int = 7,
           now: datetime = _NOW,
           handoff: TossManualHandoff | None = None):
    intent = _intent(execution_mode)
    current_handoff = handoff or _handoff(source_account_seq)
    return issue_live_execution_permit(
        approval=_consumed(execution_mode, source_account_seq),
        intent_id=intent.intent_id,
        intent_execution_mode=intent.execution_mode,
        intent_status=intent.status,
        intent_not_before=intent.not_before,
        intent_expires_at=intent.expires_at,
        intent_proposal_id=intent.proposal_id,
        intent_risk_decision_id=intent.risk_decision_id,
        handoff_intent_id=current_handoff.intent_id,
        handoff_manifest_hash=current_handoff.manifest_hash,
        handoff_account_seq=current_handoff.account_seq,
        handoff_client_order_ids=tuple(ticket.client_order_id for ticket in current_handoff.tickets),
        account_seq=account_seq,
        now=now,
    )
class ApprovalBridgeTest(unittest.TestCase):
    def test_consumed_live_approval_issues_short_account_bound_permit(self):
        permit = _issue()
        self.assertEqual(permit.grant_status, "consumed")
        self.assertEqual(permit.account_seq, 7)
        self.assertEqual(permit.allowed_client_order_ids, ("live-aapl-buy",))
        self.assertEqual(permit.approved_by_user_id, _USER)
        self.assertEqual(permit.expires_at, _NOW + timedelta(seconds=120))

    def test_paper_approval_can_never_issue_live_permit(self):
        with self.assertRaisesRegex(ExecutionSafetyError, "paper approval"):
            _issue(execution_mode="paper")

    def test_different_account_or_manifest_fails_closed(self):
        with self.assertRaisesRegex(ExecutionSafetyError, "different Toss account"):
            _issue(account_seq=8)
        tampered = replace(_handoff(), tickets=())
        with self.assertRaisesRegex(ExecutionSafetyError, "client_order_ids"):
            _issue(handoff=tampered)

    def test_unconsumed_or_expired_approval_fails_closed(self):
        unconsumed = replace(
            _consumed(), status="approved", consumed_at=None,
        )
        with self.assertRaisesRegex(ExecutionSafetyError, "atomically consumed"):
            intent = _intent()
            issue_live_execution_permit(
                approval=unconsumed,
                intent_id=intent.intent_id,
                intent_execution_mode=intent.execution_mode,
                intent_status=intent.status,
                intent_not_before=intent.not_before,
                intent_expires_at=intent.expires_at,
                intent_proposal_id=intent.proposal_id,
                intent_risk_decision_id=intent.risk_decision_id,
                handoff_intent_id=_handoff().intent_id,
                handoff_manifest_hash=_handoff().manifest_hash,
                handoff_account_seq=7,
                handoff_client_order_ids=("live-aapl-buy",),
                account_seq=7,
                now=_NOW,
            )
        with self.assertRaisesRegex(ExecutionSafetyError, "expired"):
            _issue(now=_NOW + timedelta(hours=1))


if __name__ == "__main__":
    unittest.main()
