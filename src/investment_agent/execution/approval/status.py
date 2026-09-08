"""재조정 결과를 원래 Discord 승인 카드에만 best-effort로 되돌린다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from investment_agent.execution.approval.ledger import ApprovalRequest
from investment_agent.execution.approval.discord import DiscordApprovalClient
from investment_agent.execution.reconciliation.worker import ReconciliationCardUpdate


class ApprovalStatusRepository(Protocol):
    def load_approval(self, approval_id: str) -> ApprovalRequest | None: ...


class ApprovalStatusClient(Protocol):
    @property
    def guild_id(self) -> str: ...

    def set_status_text(
        self,
        *,
        channel_id: str,
        message_id: str,
        content: str,
    ) -> None: ...


@dataclass(frozen=True)
class ApprovalStatusPublishSummary:
    sent: int
    failed: int
    skipped: int


_STATUS_TEXT = {
    "submitted": "⏳ 토스 주문이 접수되어 체결 상태를 확인하고 있습니다.",
    "partially_filled": "🟡 일부 수량이 체결되었습니다. 남은 수량을 계속 확인하고 있습니다.",
    "filled": "✅ 승인한 주문안이 전량 체결되었습니다.",
    "cancelled": "⚪ 주문이 취소 상태로 종료되었습니다. 미체결 수량은 재주문하지 않습니다.",
    "failed": "⛔ 주문이 거절·실패 상태로 종료되었습니다. 자동 재주문하지 않습니다.",
    "outcome_unknown": (
        "⚠️ 토스 접수 결과를 자동으로 확정하지 못했습니다. 같은 주문을 재전송하지 않으며 "
        "운영자 확인이 필요합니다."
    ),
}


def reconciliation_status_text(status: str) -> str:
    """허용한 broker 축약 상태만 사람용 문구로 바꾼다."""
    try:
        return _STATUS_TEXT[status]
    except KeyError as exc:
        raise ValueError("unsupported reconciliation card status") from exc


def publish_reconciliation_statuses(
    *,
    repository: ApprovalStatusRepository,
    updates: tuple[ReconciliationCardUpdate, ...],
    account_seq: int,
    bot_token: str | None,
    expected_guild_id: str | None,
    expected_channel_id: str | None,
    client_factory: Callable[..., ApprovalStatusClient] = DiscordApprovalClient,
) -> ApprovalStatusPublishSummary:
    """원장 변경 뒤 exact approval/message에만 PATCH하며 실패를 전파하지 않는다.

    승인봇 설정이 아직 없으면 조용히 skip한다. Discord 장애나 잘못된 식별자는 주문 원장,
    intent 상태, 반환 코드에 영향을 주지 않는다.
    """
    token = str(bot_token or "").strip()
    guild_id = str(expected_guild_id or "").strip()
    channel_id = str(expected_channel_id or "").strip()
    if not token or not guild_id or not channel_id:
        return ApprovalStatusPublishSummary(sent=0, failed=0, skipped=len(updates))

    sent = 0
    failed = 0
    skipped = 0
    client: ApprovalStatusClient | None = None
    for update in updates:
        try:
            approval = repository.load_approval(update.approval_id)
            if (
                approval is None
                or approval.intent_id != update.intent_id
                or approval.execution_mode != "live"
                or approval.status != "consumed"
                or approval.decision != "approved"
                or approval.account_seq != account_seq
                or approval.discord_guild_id != guild_id
                or approval.discord_channel_id != channel_id
                or approval.discord_message_id is None
            ):
                failed += 1
                continue
            if client is None:
                client = client_factory(bot_token=token, guild_id=guild_id)
            if client.guild_id != approval.discord_guild_id:
                failed += 1
                continue
            client.set_status_text(
                channel_id=approval.discord_channel_id,
                message_id=approval.discord_message_id,
                content=reconciliation_status_text(update.status),
            )
            sent += 1
        except Exception:
            # Discord는 관제 표면일 뿐이다. 여기서 원장 상태나 재실행 가능성을 바꾸지 않는다.
            failed += 1
    return ApprovalStatusPublishSummary(sent=sent, failed=failed, skipped=skipped)


__all__ = [
    "ApprovalStatusPublishSummary",
    "publish_reconciliation_statuses",
    "reconciliation_status_text",
]
