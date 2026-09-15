"""Discord 승인 요청 생성·발송·결정을 조율하되 주문은 실행하지 않는다."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol

from investment_agent.platform.serialization import parse_datetime
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.platform.logging import get_logger
from investment_agent.execution.approval.ledger import (
    ApprovalInteraction,
    ApprovalRequest,
    ApprovalSigner,
    parse_button_interaction,
)
from investment_agent.execution.approval.card import build_approval_card, button_components
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.approval.discord import DiscordApprovalClient
from investment_agent.execution.orders.toss_manual import TossManualHandoff

log = get_logger(__name__)


class ApprovalRepository(Protocol):
    def create_approval(self, request: ApprovalRequest) -> ApprovalRequest: ...
    def load_approval(self, approval_id: str) -> ApprovalRequest | None: ...
    def attach_approval_message(
        self,
        approval_id: str,
        *,
        discord_guild_id: str,
        discord_channel_id: str,
        discord_message_id: str,
    ) -> ApprovalRequest | None: ...
    def decide_approval(
        self,
        approval_id: str,
        *,
        action: str,
        discord_guild_id: str,
        discord_channel_id: str,
        discord_message_id: str,
        discord_user_id: str,
    ) -> ApprovalRequest | None: ...
    def consume_approval(
        self,
        approval_id: str,
        *,
        manifest_hash: str,
    ) -> ApprovalRequest | None: ...


class ApprovalWorkflow:
    """승인을 audit ledger에 기록하고 broker 권한과 분리한다."""

    def __init__(
        self,
        *,
        repository: ApprovalRepository,
        signer: ApprovalSigner,
        discord_client: DiscordApprovalClient | None = None,
        runtime_approver_user_ids: tuple[str, ...] = (),
    ):
        self._repository = repository
        self._signer = signer
        self._discord = discord_client
        self._runtime_approvers = frozenset(runtime_approver_user_ids)

    def create_request(
        self,
        *,
        intent: ExecutionIntent,
        handoff: TossManualHandoff,
        proposal_hash: str,
        risk_hash: str,
        discord_guild_id: str,
        discord_channel_id: str,
        allowed_approver_user_ids: tuple[str, ...],
        ttl: timedelta = timedelta(minutes=15),
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """현재 intent와 정확히 같은 manifest에 대해서만 pending 요청을 저장한다."""
        if intent.status != "approved":
            raise ExecutionSafetyError("only approved intents can request Discord approval")
        handoff.validate_manifest()
        if intent.intent_id != handoff.intent_id:
            raise ExecutionSafetyError("execution intent does not match Toss handoff")
        if not intent.proposal_id:
            raise ExecutionSafetyError("execution intent proposal_id is empty")
        requested_at = parse_datetime(now or datetime.now(timezone.utc))
        if requested_at < parse_datetime(intent.not_before):
            raise ExecutionSafetyError("execution intent is not active yet")
        if self._runtime_approvers and not set(allowed_approver_user_ids).issubset(
            self._runtime_approvers
        ):
            raise ExecutionSafetyError("request approvers are outside the runtime allowlist")
        request = ApprovalRequest.create(
            intent_id=intent.intent_id,
            proposal_id=intent.proposal_id,
            risk_decision_id=intent.risk_decision_id,
            execution_mode=intent.execution_mode,
            proposal_hash=proposal_hash,
            risk_hash=risk_hash,
            manifest_hash=handoff.manifest_hash,
            account_seq=handoff.account_seq,
            allowed_client_order_ids=tuple(
                ticket.client_order_id for ticket in handoff.tickets
            ),
            discord_guild_id=discord_guild_id,
            discord_channel_id=discord_channel_id,
            allowed_approver_user_ids=allowed_approver_user_ids,
            requested_at=requested_at,
            ttl=ttl,
            latest_expiry=intent.expires_at,
        )
        return self._repository.create_approval(request)

    def publish_request(
        self,
        request: ApprovalRequest,
        handoff: TossManualHandoff,
    ) -> ApprovalRequest:
        """pending 행을 먼저 만든 뒤 카드를 보내고 stable message ID를 한 번만 결합한다."""
        if self._discord is None:
            raise ExecutionSafetyError("Discord approval client is not configured")
        if request.status != "pending" or request.discord_message_id is not None:
            raise ExecutionSafetyError("only an unpublished pending approval can be posted")
        if self._discord.guild_id != request.discord_guild_id:
            raise ExecutionSafetyError("Discord client guild does not match approval request")
        payload = build_approval_card(request, handoff, self._signer)
        message = self._discord.post_card(
            channel_id=request.discord_channel_id,
            payload=payload,
        )
        if (
            message.guild_id != request.discord_guild_id
            or message.channel_id != request.discord_channel_id
        ):
            raise ExecutionSafetyError("Discord approval message identity does not match")
        attached = self._repository.attach_approval_message(
            request.approval_id,
            discord_guild_id=message.guild_id,
            discord_channel_id=message.channel_id,
            discord_message_id=message.message_id,
        )
        if attached is None:
            try:
                self._discord.disable_buttons(
                    channel_id=message.channel_id,
                    message_id=message.message_id,
                    components=button_components(request, self._signer, disabled=True),
                )
            except Exception as exc:  # DB 결합 실패가 본체이며 UI 정리는 최선 노력이다.
                log.warning("orphan approval card could not be disabled: %s", exc)
            raise ExecutionSafetyError("Discord message could not be attached atomically")
        return attached

    @staticmethod
    def _validate_identity(
        request: ApprovalRequest,
        interaction: ApprovalInteraction,
        *,
        now: datetime,
    ) -> None:
        if request.status != "pending" or request.discord_message_id is None:
            raise ExecutionSafetyError("Discord approval is no longer pending")
        if interaction.discord_user_id not in request.allowed_approver_user_ids:
            raise ExecutionSafetyError("Discord user is not in the approval allowlist")
        if (
            interaction.discord_guild_id != request.discord_guild_id
            or interaction.discord_channel_id != request.discord_channel_id
            or interaction.discord_message_id != request.discord_message_id
        ):
            raise ExecutionSafetyError("Discord approval message identity does not match")
        if now >= parse_datetime(request.expires_at):
            raise ExecutionSafetyError("Discord approval has expired")

    def handle_interaction(
        self,
        payload: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """서명된 button interaction 하나만 approved/rejected로 원자 전이한다."""
        interaction = parse_button_interaction(payload)
        request = self._repository.load_approval(interaction.approval_id)
        if request is None:
            raise ExecutionSafetyError("Discord approval request was not found")
        current = parse_datetime(now or datetime.now(timezone.utc))
        if self._runtime_approvers and interaction.discord_user_id not in self._runtime_approvers:
            raise ExecutionSafetyError("Discord user was removed from the runtime allowlist")
        self._validate_identity(request, interaction, now=current)
        self._signer.verify(request, interaction)
        action = "approved" if interaction.action == "approve" else "rejected"
        decided = self._repository.decide_approval(
            request.approval_id,
            action=action,
            discord_guild_id=interaction.discord_guild_id,
            discord_channel_id=interaction.discord_channel_id,
            discord_message_id=interaction.discord_message_id,
            discord_user_id=interaction.discord_user_id,
        )
        if decided is None:
            raise ExecutionSafetyError("Discord approval was duplicate, expired, or concurrent")
        if self._discord is not None:
            try:
                self._discord.disable_buttons(
                    channel_id=decided.discord_channel_id,
                    message_id=str(decided.discord_message_id),
                    components=button_components(decided, self._signer, disabled=True),
                )
            except Exception as exc:  # 원자 DB 결과는 UI 편집 실패와 무관하게 유지한다.
                log.warning("decided approval buttons could not be disabled: %s", exc)
        return decided

    def consume_once(self, *, approval_id: str, expected_manifest_hash: str) -> ApprovalRequest:
        """향후 worker용 1회성 gate다. 여기서는 주문을 호출하지 않는다."""
        request = self._repository.load_approval(approval_id)
        if request is None or request.status != "approved":
            raise ExecutionSafetyError("approval is not available for consumption")
        if request.manifest_hash != expected_manifest_hash:
            raise ExecutionSafetyError("approval plan hash changed before consumption")
        consumed = self._repository.consume_approval(
            approval_id,
            manifest_hash=expected_manifest_hash,
        )
        if consumed is None:
            raise ExecutionSafetyError("approval was already consumed or expired")
        return consumed
