from __future__ import annotations

import hashlib
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.execution.approval.ledger import ApprovalRequest, ApprovalSigner, parse_button_interaction
from investment_agent.execution.approval.card import build_approval_card, button_components
from investment_agent.execution.approval.service import ApprovalWorkflow
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.approval.discord import DiscordMessageRef
from investment_agent.execution.approval.discord import DiscordApprovalClient
from investment_agent.execution.orders.toss_manual import TossManualHandoff, TossManualSnapshot, TossManualTicket

_NOW = datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc)
_GUILD = "1510267057885941840"
_CHANNEL = "1539250099999999999"
_MESSAGE = "1539250199999999999"
_USER = "1537373837350404146"
_OTHER_USER = "1537373837350404147"
_SECRET = "approval-test-secret-that-is-longer-than-thirty-two-bytes"


def _intent() -> ExecutionIntent:
    return ExecutionIntent(
        intent_id="intent-approval-test",
        risk_decision_id="risk-test",
        proposal_id="proposal-test",
        execution_mode="paper",
        target_weights={"AAPL": 0.1, "CASH": 0.9},
        input_hash=hashlib.sha256(b"intent").hexdigest(),
        not_before=(_NOW - timedelta(minutes=1)).isoformat(),
        expires_at=(_NOW + timedelta(hours=1)).isoformat(),
    )


def _handoff() -> TossManualHandoff:
    handoff = TossManualHandoff(
        intent_id="intent-approval-test",
        account_seq=7,
        contract_version="toss-manual-v1",
        snapshot=TossManualSnapshot(
            captured_at=_NOW.isoformat(),
            currency="USD",
            portfolio_value=10_000,
            cash_buying_power=10_000,
            current_quantities={},
            prices={"AAPL": 200.0},
            price_timestamps={"AAPL": _NOW.isoformat()},
        ),
        tickets=(TossManualTicket(
            intent_id="intent-approval-test",
            client_order_id="order-aapl",
            expires_at=(_NOW + timedelta(hours=1)).isoformat(),
            symbol="AAPL",
            side="buy",
            current_quantity=0,
            target_weight=0.1,
            target_quantity=5,
            order_quantity=5,
            reference_price=200,
            price_timestamp=_NOW.isoformat(),
            estimated_notional=1_000,
        ),),
        manifest_hash="0" * 64,
    )
    return replace(handoff, manifest_hash=handoff.recomputed_manifest_hash())


class _Repository:
    def __init__(self):
        self.rows: dict[str, ApprovalRequest] = {}
        self.lock = threading.Lock()

    def create_approval(self, request: ApprovalRequest) -> ApprovalRequest:
        with self.lock:
            if any(row.intent_id == request.intent_id for row in self.rows.values()):
                raise RuntimeError("active approval already exists")
            self.rows[request.approval_id] = request
            return request

    def load_approval(self, approval_id: str) -> ApprovalRequest | None:
        with self.lock:
            return self.rows.get(approval_id)

    def attach_approval_message(self, approval_id: str, **ids) -> ApprovalRequest | None:
        with self.lock:
            row = self.rows.get(approval_id)
            if row is None or row.status != "pending" or row.discord_message_id is not None:
                return None
            if (
                row.discord_guild_id != ids["discord_guild_id"]
                or row.discord_channel_id != ids["discord_channel_id"]
            ):
                return None
            attached = replace(row, discord_message_id=ids["discord_message_id"])
            self.rows[approval_id] = attached
            return attached

    def decide_approval(self, approval_id: str, **values) -> ApprovalRequest | None:
        with self.lock:
            row = self.rows.get(approval_id)
            if row is None or row.status != "pending":
                return None
            if (
                row.discord_guild_id != values["discord_guild_id"]
                or row.discord_channel_id != values["discord_channel_id"]
                or row.discord_message_id != values["discord_message_id"]
                or values["discord_user_id"] not in row.allowed_approver_user_ids
            ):
                return None
            decided = replace(
                row,
                status=values["action"],
                decision=values["action"],
                decided_at=_NOW.isoformat(),
                decided_by_user_id=values["discord_user_id"],
            )
            self.rows[approval_id] = decided
            return decided

    def consume_approval(self, approval_id: str, *, manifest_hash: str) -> ApprovalRequest | None:
        with self.lock:
            row = self.rows.get(approval_id)
            if row is None or row.status != "approved" or row.manifest_hash != manifest_hash:
                return None
            consumed = replace(row, status="consumed", consumed_at=_NOW.isoformat())
            self.rows[approval_id] = consumed
            return consumed


class _Discord:
    guild_id = _GUILD

    def __init__(self):
        self.payload = None
        self.disabled = 0

    def post_card(self, *, channel_id, payload):
        self.payload = payload
        return DiscordMessageRef(_GUILD, channel_id, _MESSAGE)

    def disable_buttons(self, **_kwargs):
        self.disabled += 1


class _Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class _Session:
    def __init__(self, response):
        self.response = response
        self.posts = []

    def post(self, *args, **kwargs):
        self.posts.append((args, kwargs))
        return self.response


def _interaction(request: ApprovalRequest, signer: ApprovalSigner, *, user: str = _USER) -> dict:
    return {
        "type": 3,
        "data": {
            "component_type": 2,
            "custom_id": signer.custom_id(request, "approve"),
        },
        "guild_id": _GUILD,
        "channel_id": _CHANNEL,
        "message": {"id": _MESSAGE},
        "member": {"user": {"id": user}},
    }


class ApprovalContractTest(unittest.TestCase):
    def test_custom_id_is_signed_and_tamper_evident(self):
        signer = ApprovalSigner(_SECRET)
        request = ApprovalRequest.create(
            intent_id="intent", proposal_id="proposal", risk_decision_id="risk",
            execution_mode="paper",
            proposal_hash="a" * 64, risk_hash="b" * 64, manifest_hash="c" * 64,
            account_seq=7, allowed_client_order_ids=("order-aapl",),
            discord_guild_id=_GUILD, discord_channel_id=_CHANNEL,
            allowed_approver_user_ids=(_USER,), requested_at=_NOW,
        )
        payload = _interaction(replace(request, discord_message_id=_MESSAGE), signer)
        parsed = parse_button_interaction(payload)
        signer.verify(request, parsed)
        self.assertLessEqual(len(payload["data"]["custom_id"]), 100)

        last = payload["data"]["custom_id"][-1]
        payload["data"]["custom_id"] = payload["data"]["custom_id"][:-1] + (
            "B" if last == "A" else "A"
        )
        with self.assertRaisesRegex(ExecutionSafetyError, "signature"):
            signer.verify(request, parse_button_interaction(payload))

    def test_text_reply_reaction_and_non_button_are_never_approval(self):
        for payload in (
            {"type": 2, "data": {"name": "승인"}},
            {"type": "MESSAGE_REACTION_ADD", "emoji": {"name": "✅"}},
            {"type": 3, "data": {"component_type": 3, "custom_id": "승인"}},
            {"type": 3, "data": {"component_type": 2, "custom_id": "승인"}},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ExecutionSafetyError):
                    parse_button_interaction(payload)


class ApprovalWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.repository = _Repository()
        self.signer = ApprovalSigner(_SECRET)
        self.discord = _Discord()
        self.workflow = ApprovalWorkflow(
            repository=self.repository,
            signer=self.signer,
            discord_client=self.discord,
        )

    def _published(self) -> ApprovalRequest:
        request = self.workflow.create_request(
            intent=_intent(), handoff=_handoff(), proposal_hash="a" * 64,
            risk_hash="b" * 64, discord_guild_id=_GUILD,
            discord_channel_id=_CHANNEL, allowed_approver_user_ids=(_USER,), now=_NOW,
        )
        return self.workflow.publish_request(request, _handoff())

    def test_card_binds_all_hashes_and_has_only_signed_buttons(self):
        request = self._published()
        payload = self.discord.payload
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(len(payload["components"][0]["components"]), 2)
        self.assertIn(request.proposal_hash, str(payload["embeds"]))
        self.assertIn(request.risk_hash, str(payload["embeds"]))
        self.assertIn(request.manifest_hash, str(payload["embeds"]))
        self.assertIn("permit으로 바뀌지 않습니다", str(payload["embeds"]))

    def test_allowlisted_button_approves_once_then_consumes_once(self):
        request = self._published()
        decided = self.workflow.handle_interaction(
            _interaction(request, self.signer), now=_NOW,
        )
        self.assertEqual(decided.status, "approved")
        self.assertEqual(decided.decided_by_user_id, _USER)
        self.assertEqual(self.discord.disabled, 1)
        with self.assertRaises(ExecutionSafetyError):
            self.workflow.handle_interaction(_interaction(request, self.signer), now=_NOW)

        consumed = self.workflow.consume_once(
            approval_id=request.approval_id,
            expected_manifest_hash=request.manifest_hash,
        )
        self.assertEqual(consumed.status, "consumed")
        with self.assertRaises(ExecutionSafetyError):
            self.workflow.consume_once(
                approval_id=request.approval_id,
                expected_manifest_hash=request.manifest_hash,
            )

    def test_wrong_user_fails_before_database_transition(self):
        request = self._published()
        with self.assertRaisesRegex(ExecutionSafetyError, "allowlist"):
            self.workflow.handle_interaction(
                _interaction(request, self.signer, user=_OTHER_USER), now=_NOW,
            )
        self.assertEqual(self.repository.load_approval(request.approval_id).status, "pending")

    def test_wrong_guild_channel_or_message_fails_before_database_transition(self):
        request = self._published()
        for field, value in (
            ("guild_id", "1510267057885941841"),
            ("channel_id", "1539250099999999998"),
        ):
            payload = _interaction(request, self.signer)
            payload[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                ExecutionSafetyError, "identity"
            ):
                self.workflow.handle_interaction(payload, now=_NOW)

        payload = _interaction(request, self.signer)
        payload["message"]["id"] = "1539250199999999998"
        with self.assertRaisesRegex(ExecutionSafetyError, "identity"):
            self.workflow.handle_interaction(payload, now=_NOW)
        self.assertEqual(
            self.repository.load_approval(request.approval_id).status,
            "pending",
        )

    def test_expired_or_runtime_revoked_approval_fails_closed(self):
        request = self._published()
        with self.assertRaisesRegex(ExecutionSafetyError, "expired"):
            self.workflow.handle_interaction(
                _interaction(request, self.signer),
                now=_NOW + timedelta(hours=2),
            )

        revoked = ApprovalWorkflow(
            repository=self.repository,
            signer=self.signer,
            runtime_approver_user_ids=(_OTHER_USER,),
        )
        with self.assertRaisesRegex(ExecutionSafetyError, "removed"):
            revoked.handle_interaction(_interaction(request, self.signer), now=_NOW)

    def test_concurrent_duplicate_is_fail_closed(self):
        request = self._published()
        payload = _interaction(request, self.signer)

        def approve() -> str:
            try:
                return self.workflow.handle_interaction(payload, now=_NOW).status
            except ExecutionSafetyError:
                return "blocked"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: approve(), range(2)))
        self.assertCountEqual(results, ["approved", "blocked"])

    def test_card_builder_rejects_different_manifest_hash(self):
        request = self._published()
        changed = replace(_handoff(), account_seq=8)
        with self.assertRaisesRegex(ExecutionSafetyError, "manifest contents"):
            build_approval_card(request, changed, self.signer)

    def test_disabled_components_keep_exact_signed_ids(self):
        request = self._published()
        enabled = button_components(request, self.signer)
        disabled = button_components(request, self.signer, disabled=True)
        for before, after in zip(
            enabled[0]["components"], disabled[0]["components"], strict=True,
        ):
            self.assertEqual(before["custom_id"], after["custom_id"])
            self.assertTrue(after["disabled"])


class DiscordApprovalClientTest(unittest.TestCase):
    def test_card_is_posted_once_without_mentions(self):
        session = _Session(_Response({"id": _MESSAGE, "channel_id": _CHANNEL}))
        client = DiscordApprovalClient(
            bot_token="rotated-test-token",
            guild_id=_GUILD,
            session=session,
        )
        ref = client.post_card(
            channel_id=_CHANNEL,
            payload={
                "components": [{"type": 1, "components": []}],
                "allowed_mentions": {"parse": []},
            },
        )
        self.assertEqual(ref, DiscordMessageRef(_GUILD, _CHANNEL, _MESSAGE))
        self.assertEqual(len(session.posts), 1)
        sent = session.posts[0][1]
        self.assertEqual(sent["json"]["allowed_mentions"], {"parse": []})
        self.assertNotIn("rotated-test-token", str(sent["json"]))

    def test_unexpected_returned_channel_fails_closed(self):
        session = _Session(_Response({"id": _MESSAGE, "channel_id": "1539250099999999998"}))
        client = DiscordApprovalClient(
            bot_token="rotated-test-token", guild_id=_GUILD, session=session,
        )
        with self.assertRaisesRegex(ExecutionSafetyError, "unexpected"):
            client.post_card(
                channel_id=_CHANNEL,
                payload={"components": [{"type": 1, "components": []}]},
            )


if __name__ == "__main__":
    unittest.main()
