"""토스 live Discord 승인 요청 진입점의 오프라인 경계 테스트."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.execution.approval.ledger import ApprovalRequest
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.operations.commands.request_toss_approval import (
    ApprovalRuntimeConfig,
    canonical_row_sha256,
    request_toss_approval,
    request_toss_approval_by_id,
)
from investment_agent.execution.orders.planning import ExecutionLimits, TargetWeightOrderPlanner
from investment_agent.execution.orders.toss_manual import (
    TossManualHandoff,
    TossManualSnapshot,
    TossManualTicket,
    prepare_handoff,
)

_NOW = datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc)
_GUILD = "1510267057885941840"
_CHANNEL = "1539250099999999999"
_MESSAGE = "1539250199999999999"
_APPROVER = "1537373837350404146"
_SECRET = "approval-test-secret-that-is-longer-than-thirty-two-bytes"


def _intent(*, execution_mode: str = "live", status: str = "approved") -> ExecutionIntent:
    return ExecutionIntent(
        intent_id="intent-live-request",
        risk_decision_id="risk-live-request",
        proposal_id="proposal-live-request",
        execution_mode=execution_mode,
        target_weights={"AAPL": 0.1, "CASH": 0.9},
        input_hash=hashlib.sha256(b"risk-input").hexdigest(),
        not_before=(_NOW - timedelta(minutes=1)).isoformat(),
        expires_at=(_NOW + timedelta(hours=1)).isoformat(),
        status=status,
    )


def _proposal() -> dict:
    return {
        "proposal_id": "proposal-live-request",
        "run_id": "run-live-request",
        "stage": "live",
        "weights": {"AAPL": 0.1, "CASH": 0.9},
        "metadata": {"execution_eligible": True},
        "created_at": "2026-08-22T03:58:00+00:00",
    }


def _risk() -> dict:
    return {
        "risk_decision_id": "risk-live-request",
        "proposal_id": "proposal-live-request",
        "approved": True,
        "approved_weights": {"AAPL": 0.1, "CASH": 0.9},
        "violations": [],
        "input_hash": hashlib.sha256(b"risk-input").hexdigest(),
        "decided_at": "2026-08-22T03:59:00+00:00",
    }


def _handoff(
    *,
    captured_at: datetime = _NOW,
    quote_at: datetime | None = _NOW,
    quantity: float = 5.0,
) -> TossManualHandoff:
    timestamp = quote_at.isoformat() if quote_at is not None else None
    handoff = TossManualHandoff(
        intent_id="intent-live-request",
        account_seq=7,
        contract_version="toss-manual-v1",
        snapshot=TossManualSnapshot(
            captured_at=captured_at.isoformat(),
            currency="USD",
            portfolio_value=10_000.0,
            cash_buying_power=10_000.0,
            current_quantities={},
            prices={"AAPL": 200.0},
            price_timestamps={"AAPL": timestamp},
        ),
        tickets=(TossManualTicket(
            intent_id="intent-live-request",
            client_order_id="aix_live_aapl",
            expires_at=(_NOW + timedelta(hours=1)).isoformat(),
            symbol="AAPL",
            side="buy",
            current_quantity=0.0,
            target_weight=0.1,
            target_quantity=5.0,
            order_quantity=quantity,
            reference_price=200.0,
            price_timestamp=timestamp,
            estimated_notional=quantity * 200.0,
        ),),
        manifest_hash="0" * 64,
    )
    return replace(handoff, manifest_hash=handoff.recomputed_manifest_hash())


def _config() -> ApprovalRuntimeConfig:
    return ApprovalRuntimeConfig(
        guild_id=_GUILD,
        channel_id=_CHANNEL,
        approver_user_ids=(_APPROVER,),
        bot_token="test-bot-token",
        hmac_secret=_SECRET,
    )


def _planner(*, whole_shares: bool = True) -> TargetWeightOrderPlanner:
    return TargetWeightOrderPlanner(ExecutionLimits(
        min_order_notional=1.0,
        max_order_notional=10_000.0,
        max_total_notional=20_000.0,
        quantity_decimals=0 if whole_shares else 6,
    ))


class _ExecutionRepository:
    def __init__(
        self,
        *,
        intent: ExecutionIntent | None = None,
        approval: ApprovalRequest | None = None,
        eligible: set[str] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.intent = intent if intent is not None else _intent()
        self.approval = approval
        self.eligible = {"AAPL"} if eligible is None else set(eligible)
        self.events = events if events is not None else []
        self.saved_handoffs: list[TossManualHandoff] = []

    def load_intent(self, intent_id: str) -> ExecutionIntent | None:
        self.events.append("load_intent")
        if self.intent is not None and self.intent.intent_id == intent_id:
            return self.intent
        return None

    def approval_for_intent(self, intent_id: str) -> ApprovalRequest | None:
        self.events.append("approval_for_intent")
        if self.approval is not None and self.approval.intent_id == intent_id:
            return self.approval
        return None

    def current_tracked_tickers(self) -> set[str]:
        self.events.append("tracked_universe")
        return set(self.eligible)

    def save_handoff(self, handoff: TossManualHandoff) -> None:
        self.events.append("save_handoff")
        self.saved_handoffs.append(handoff)


class _DecisionRepository:
    def __init__(self, proposal: dict | None = None, risk: dict | None = None):
        self.proposal = _proposal() if proposal is None else proposal
        self.risk = _risk() if risk is None else risk

    def portfolio_proposal(self, proposal_id: str) -> dict | None:
        return self.proposal if self.proposal.get("proposal_id") == proposal_id else None

    def risk_decision(self, risk_decision_id: str) -> dict | None:
        return self.risk if self.risk.get("risk_decision_id") == risk_decision_id else None


class _Workflow:
    def __init__(
        self,
        repository: _ExecutionRepository,
        *,
        timeout_on_publish: bool = False,
    ) -> None:
        self.repository = repository
        self.timeout_on_publish = timeout_on_publish
        self.create_calls: list[dict] = []
        self.publish_calls = 0

    def create_request(self, **kwargs) -> ApprovalRequest:
        self.repository.events.append("create_request")
        self.create_calls.append(kwargs)
        request = ApprovalRequest.create(
            intent_id=kwargs["intent"].intent_id,
            proposal_id=kwargs["intent"].proposal_id,
            risk_decision_id=kwargs["intent"].risk_decision_id,
            execution_mode=kwargs["intent"].execution_mode,
            proposal_hash=kwargs["proposal_hash"],
            risk_hash=kwargs["risk_hash"],
            manifest_hash=kwargs["handoff"].manifest_hash,
            account_seq=kwargs["handoff"].account_seq,
            allowed_client_order_ids=tuple(
                row.client_order_id for row in kwargs["handoff"].tickets
            ),
            discord_guild_id=kwargs["discord_guild_id"],
            discord_channel_id=kwargs["discord_channel_id"],
            allowed_approver_user_ids=kwargs["allowed_approver_user_ids"],
            requested_at=kwargs["now"],
            ttl=kwargs["ttl"],
            latest_expiry=kwargs["intent"].expires_at,
        )
        self.repository.approval = request
        return request

    def publish_request(
        self,
        request: ApprovalRequest,
        handoff: TossManualHandoff,
    ) -> ApprovalRequest:
        self.repository.events.append("publish_request")
        self.publish_calls += 1
        if self.timeout_on_publish:
            raise TimeoutError("Discord POST outcome is unknown")
        published = replace(request, discord_message_id=_MESSAGE)
        self.repository.approval = published
        return published


def _existing(*, message_id: str | None) -> ApprovalRequest:
    return ApprovalRequest.create(
        intent_id=_intent().intent_id,
        proposal_id=_intent().proposal_id,
        risk_decision_id=_intent().risk_decision_id,
        execution_mode="live",
        proposal_hash="a" * 64,
        risk_hash="b" * 64,
        manifest_hash=_handoff().manifest_hash,
        account_seq=7,
        allowed_client_order_ids=("aix_live_aapl",),
        discord_guild_id=_GUILD,
        discord_channel_id=_CHANNEL,
        allowed_approver_user_ids=(_APPROVER,),
        requested_at=_NOW,
        latest_expiry=_intent().expires_at,
    ) if message_id is None else replace(
        ApprovalRequest.create(
            intent_id=_intent().intent_id,
            proposal_id=_intent().proposal_id,
            risk_decision_id=_intent().risk_decision_id,
            execution_mode="live",
            proposal_hash="a" * 64,
            risk_hash="b" * 64,
            manifest_hash=_handoff().manifest_hash,
            account_seq=7,
            allowed_client_order_ids=("aix_live_aapl",),
            discord_guild_id=_GUILD,
            discord_channel_id=_CHANNEL,
            allowed_approver_user_ids=(_APPROVER,),
            requested_at=_NOW,
            latest_expiry=_intent().expires_at,
        ),
        discord_message_id=message_id,
    )


class RuntimeConfigTest(unittest.TestCase):
    def _env(self) -> dict[str, str]:
        return {
            "DISCORD_GUILD_ID": _GUILD,
            "DISCORD_CHANNEL_AI_APPROVALS": _CHANNEL,
            "DISCORD_APPROVER_USER_IDS": _APPROVER,
            "DISCORD_APPROVAL_BOT_TOKEN": "test-token",
            "DISCORD_APPROVAL_HMAC_SECRET": _SECRET,
        }

    def test_exact_discord_identity_allowlist_and_hmac_are_required(self):
        for name in (
            "DISCORD_GUILD_ID",
            "DISCORD_CHANNEL_AI_APPROVALS",
            "DISCORD_APPROVER_USER_IDS",
            "DISCORD_APPROVAL_BOT_TOKEN",
        ):
            env = self._env()
            env.pop(name)
            with self.subTest(name=name), self.assertRaises(ExecutionSafetyError):
                ApprovalRuntimeConfig.from_env(env)

        bad = self._env()
        bad["DISCORD_GUILD_ID"] = "guild-name"
        with self.assertRaises(ExecutionSafetyError):
            ApprovalRuntimeConfig.from_env(bad)
        short = self._env()
        short["DISCORD_APPROVAL_HMAC_SECRET"] = "too-short"
        with self.assertRaises(ExecutionSafetyError):
            ApprovalRuntimeConfig.from_env(short)

    def test_missing_inline_hmac_is_created_in_an_explicit_private_file(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self._env()
            env.pop("DISCORD_APPROVAL_HMAC_SECRET")
            env["DISCORD_APPROVAL_HMAC_SECRET_FILE"] = str(
                Path(temp) / "approval.key"
            )
            first = ApprovalRuntimeConfig.from_env(env)
            second = ApprovalRuntimeConfig.from_env(env)
        self.assertEqual(first.hmac_secret, second.hmac_secret)
        self.assertGreaterEqual(len(first.hmac_secret.encode("utf-8")), 32)

    def test_canonical_hash_is_key_order_independent(self):
        self.assertEqual(
            canonical_row_sha256({"b": 2, "a": 1}),
            canonical_row_sha256({"a": 1, "b": 2}),
        )


class RequestTossApprovalTest(unittest.TestCase):
    def _request(
        self,
        repository: _ExecutionRepository,
        *,
        decisions: _DecisionRepository | None = None,
        workflow: _Workflow | None = None,
        planner: TargetWeightOrderPlanner | None = None,
        prepare_fn=None,
    ) -> ApprovalRequest:
        selected_workflow = workflow or _Workflow(repository)
        selected_prepare = prepare_fn or (lambda _intent, **_kwargs: _handoff())
        return request_toss_approval(
            _intent().intent_id,
            account_seq=7,
            config=_config(),
            execution_repository=repository,
            decision_repository=decisions or _DecisionRepository(),
            workflow=selected_workflow,
            planner=planner or _planner(),
            prepare_handoff_fn=selected_prepare,
            now=_NOW,
        )

    def test_live_flow_requeries_and_saves_before_create_then_publishes(self):
        events: list[str] = []
        repository = _ExecutionRepository(events=events)
        workflow = _Workflow(repository)
        prepared: dict = {}

        def prepare_fn(intent, **kwargs):
            events.append("prepare_handoff")
            prepared.update(kwargs)
            return _handoff()

        result = self._request(
            repository, workflow=workflow, prepare_fn=prepare_fn
        )

        self.assertEqual(result.discord_message_id, _MESSAGE)
        self.assertEqual(
            [
                item for item in events
                if item in {
                    "tracked_universe", "prepare_handoff", "save_handoff",
                    "create_request", "publish_request",
                }
            ],
            [
                "tracked_universe", "prepare_handoff", "save_handoff",
                "create_request", "publish_request",
            ],
        )
        self.assertEqual(prepared["required_mode"], "live")
        self.assertEqual(prepared["eligible_buy_symbols"], {"AAPL"})
        self.assertEqual(prepared["planner"].limits.quantity_decimals, 0)
        create = workflow.create_calls[0]
        self.assertEqual(create["proposal_hash"], canonical_row_sha256(_proposal()))
        self.assertEqual(create["risk_hash"], canonical_row_sha256(_risk()))

    def test_blank_or_ambiguous_intent_id_fails_before_repository_read(self):
        for intent_id in ("", " intent-live-request "):
            repository = _ExecutionRepository()
            with self.subTest(intent_id=intent_id), self.assertRaisesRegex(
                ExecutionSafetyError, "exact execution intent_id"
            ):
                request_toss_approval(
                    intent_id,
                    account_seq=7,
                    config=_config(),
                    execution_repository=repository,
                    decision_repository=_DecisionRepository(),
                    workflow=_Workflow(repository),
                    planner=_planner(),
                    prepare_handoff_fn=lambda _intent, **_kwargs: _handoff(),
                    now=_NOW,
                )
            self.assertEqual(repository.events, [])

    def test_only_approved_live_intent_and_whole_share_planner_are_allowed(self):
        for intent in (
            _intent(execution_mode="paper"),
            _intent(status="claimed"),
        ):
            repository = _ExecutionRepository(intent=intent)
            with self.subTest(execution_mode=intent.execution_mode, status=intent.status):
                with self.assertRaises(ExecutionSafetyError):
                    self._request(repository)
                self.assertNotIn("tracked_universe", repository.events)

        with self.assertRaisesRegex(ExecutionSafetyError, "whole shares"):
            self._request(
                _ExecutionRepository(), planner=_planner(whole_shares=False)
            )

    def test_stale_missing_quote_or_fractional_handoff_fails_before_save(self):
        cases = (
            _handoff(captured_at=_NOW - timedelta(minutes=3)),
            _handoff(quote_at=None),
            _handoff(quantity=1.5),
        )
        for handoff in cases:
            repository = _ExecutionRepository()
            with self.subTest(handoff=handoff), self.assertRaises(ExecutionSafetyError):
                self._request(
                    repository,
                    prepare_fn=lambda _intent, **_kwargs: handoff,
                )
            self.assertEqual(repository.saved_handoffs, [])

    def test_ticket_must_be_bound_to_the_fresh_snapshot_quote(self):
        handoff = _handoff()
        changed_ticket = replace(handoff.tickets[0], reference_price=201.0)
        changed = replace(handoff, tickets=(changed_ticket,), manifest_hash="0" * 64)
        changed = replace(changed, manifest_hash=changed.recomputed_manifest_hash())
        repository = _ExecutionRepository()

        with self.assertRaisesRegex(ExecutionSafetyError, "reference price changed"):
            self._request(
                repository,
                prepare_fn=lambda _intent, **_kwargs: changed,
            )

        self.assertEqual(repository.saved_handoffs, [])

    def test_empty_tracked_universe_fails_before_toss_read(self):
        repository = _ExecutionRepository(eligible=set())
        prepare_fn = mock.Mock(return_value=_handoff())
        with self.assertRaisesRegex(ExecutionSafetyError, "universe is empty"):
            self._request(repository, prepare_fn=prepare_fn)
        prepare_fn.assert_not_called()

    def test_open_orders_from_real_prepare_handoff_fail_closed(self):
        repository = _ExecutionRepository()
        with (
            mock.patch(
                "investment_agent.execution.orders.toss_manual.toss.fetch_open_orders",
                return_value=[{"symbol": "AAPL"}],
            ) as open_orders,
            self.assertRaisesRegex(ExecutionSafetyError, "open orders"),
        ):
            self._request(repository, prepare_fn=prepare_handoff)
        open_orders.assert_called_once_with(7)
        self.assertEqual(repository.saved_handoffs, [])

    def test_source_row_mismatch_fails_before_toss_read(self):
        risk = _risk()
        risk["input_hash"] = "f" * 64
        repository = _ExecutionRepository()
        prepare_fn = mock.Mock(return_value=_handoff())
        with self.assertRaisesRegex(ExecutionSafetyError, "input hash"):
            self._request(
                repository,
                decisions=_DecisionRepository(risk=risk),
                prepare_fn=prepare_fn,
            )
        prepare_fn.assert_not_called()

    def test_posted_existing_request_is_idempotent_without_new_card(self):
        existing = _existing(message_id=_MESSAGE)
        repository = _ExecutionRepository(
            intent=_intent(status="completed"), approval=existing
        )
        workflow = _Workflow(repository)
        prepare_fn = mock.Mock(return_value=_handoff())

        result = self._request(
            repository, workflow=workflow, prepare_fn=prepare_fn
        )

        self.assertIs(result, existing)
        prepare_fn.assert_not_called()
        self.assertEqual(workflow.create_calls, [])
        self.assertEqual(workflow.publish_calls, 0)

    def test_ops_runtime_api_requires_explicit_stable_intent_id(self):
        repository = _ExecutionRepository()
        workflow = _Workflow(repository)
        with mock.patch(
            "investment_agent.operations.commands.request_toss_approval.toss.resolve_account_seq",
            return_value=7,
        ) as resolve_account:
            result = request_toss_approval_by_id(
                "intent-live-request",
                account_seq=7,
                config=_config(),
                execution_repository=repository,
                decision_repository=_DecisionRepository(),
                workflow=workflow,
                planner=_planner(),
                prepare_handoff_fn=lambda _intent, **_kwargs: _handoff(),
                now=_NOW,
            )

        self.assertEqual(result.intent_id, "intent-live-request")
        resolve_account.assert_not_called()

    def test_ops_runtime_api_resolves_account_only_when_not_explicit(self):
        repository = _ExecutionRepository()
        workflow = _Workflow(repository)
        with mock.patch(
            "investment_agent.operations.commands.request_toss_approval.toss.resolve_account_seq",
            return_value=7,
        ) as resolve_account:
            result = request_toss_approval_by_id(
                "intent-live-request",
                config=_config(),
                execution_repository=repository,
                decision_repository=_DecisionRepository(),
                workflow=workflow,
                planner=_planner(),
                prepare_handoff_fn=lambda _intent, **_kwargs: _handoff(),
                now=_NOW,
            )

        self.assertEqual(result.intent_id, "intent-live-request")
        resolve_account.assert_called_once_with(None)

    def test_unbound_existing_request_blocks_automatic_repost(self):
        repository = _ExecutionRepository(approval=_existing(message_id=None))
        workflow = _Workflow(repository)
        with self.assertRaisesRegex(ExecutionSafetyError, "repost is forbidden"):
            self._request(repository, workflow=workflow)
        self.assertEqual(workflow.publish_calls, 0)

    def test_discord_post_timeout_is_attempted_once_and_retry_stays_blocked(self):
        repository = _ExecutionRepository()
        workflow = _Workflow(repository, timeout_on_publish=True)
        with self.assertRaises(TimeoutError):
            self._request(repository, workflow=workflow)
        self.assertEqual(workflow.publish_calls, 1)
        self.assertIsNotNone(repository.approval)
        self.assertIsNone(repository.approval.discord_message_id)

        with self.assertRaisesRegex(ExecutionSafetyError, "repost is forbidden"):
            self._request(repository, workflow=workflow)
        self.assertEqual(workflow.publish_calls, 1)


if __name__ == "__main__":
    unittest.main()
