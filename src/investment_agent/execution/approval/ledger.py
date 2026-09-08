"""사람의 승인. 실주문으로 가는 유일한 문이다.

승인 요청·서명·permit 발급을 이 execution owner 안에서 함께 정의한다.

## 버튼은 그 계획에만 유효하다

Discord 버튼의 `custom_id`에 승인 id·만료 시각·**계획의 모든 지문**(제안·위험·주문
manifest)·계좌·주문 id 목록·서버/채널을 묶어 HMAC으로 서명한다. 그래서 어제 카드의
버튼을 오늘 계획에 쓸 수 없고, 다른 계좌·다른 채널로 옮겨 쓸 수도 없다.

서명하지 않으면 버튼 하나가 "무엇이든 승인"이 된다 — Discord는 그 버튼이 어느 계획에
붙어 있었는지 알려주지 않기 때문이다.

## 버튼만 받는다

이모지 반응이나 답장은 승인이 아니다. `parse_button_interaction`은 정확히
message-component(type 3) 중 button(component_type 2)만 통과시킨다. 느슨하게 받으면
실수로 누른 반응이 주문이 된다.

## 승인은 한 번만 쓰인다

`consumed` 상태가 그것을 말한다. 원자적으로 소비한 승인만 permit이 되고, permit은
몇 분짜리다 — 승인과 주문 사이가 벌어질수록 그 사이에 세상이 달라진다.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from investment_agent.execution.safety.control import ExecutionSafetyError
from investment_agent.platform.clock import ensure_aware, utc_now
from investment_agent.platform.serialization import parse_datetime

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
# Discord snowflake. 길이를 좁게 잡아 임의의 숫자가 사용자 id로 통과하지 않게 한다.
SNOWFLAKE_RE = re.compile(r"^[1-9][0-9]{5,24}$")
APPROVAL_ID_RE = re.compile(r"^approval_[0-9a-f]{32}$")
CUSTOM_ID_RE = re.compile(
    r"^eap1:(?P<action>[ar]):(?P<approval_id>approval_[0-9a-f]{32}):"
    # epoch는 9~12자리다. 느슨하게 잡으면 `0` 같은 값이 만료 시각으로 통과하고,
    # 그 버튼은 언제나 유효해 보인다.
    r"(?P<expires>[1-9][0-9]{8,11}):(?P<signature>[A-Za-z0-9_-]{22})$"
)

STATUSES = ("pending", "approved", "rejected", "expired", "consumed")
ACTIONS = ("approve", "reject")

# Discord custom_id 길이 상한. 넘으면 버튼이 아예 안 만들어진다.
MAX_CUSTOM_ID = 100
# 승인 요청이 살아 있는 최대 시간.
MAX_APPROVAL_TTL = timedelta(hours=24)
# permit 수명. 짧게 두는 것이 요점이다.
MIN_PERMIT_TTL_SECONDS = 1
MAX_PERMIT_TTL_SECONDS = 300


def snowflake(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not SNOWFLAKE_RE.fullmatch(text):
        raise ExecutionSafetyError(f"invalid Discord {field_name}")
    return text


def sha256_field(value: Any, field_name: str) -> str:
    text = str(value or "").strip().lower()
    if not HASH_RE.fullmatch(text):
        raise ExecutionSafetyError(f"{field_name} must be a sha256 hex digest")
    return text


def create_approval_id() -> str:
    return f"approval_{secrets.token_hex(16)}"


@dataclass(frozen=True)
class ApprovalRequest:
    """특정 주문 계획 하나에만 유효한 건별 사람 승인."""

    approval_id: str
    intent_id: str
    proposal_id: str
    risk_decision_id: str
    execution_mode: str
    proposal_hash: str
    risk_hash: str
    manifest_hash: str
    account_seq: int
    allowed_client_order_ids: tuple[str, ...]
    status: str
    discord_guild_id: str
    discord_channel_id: str
    discord_message_id: str | None
    allowed_approver_user_ids: tuple[str, ...]
    requested_at: datetime
    expires_at: datetime
    decision: str | None = None
    decided_at: datetime | None = None
    decided_by_user_id: str | None = None
    consumed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not APPROVAL_ID_RE.fullmatch(self.approval_id):
            raise ExecutionSafetyError("invalid approval_id")
        for name in ("intent_id", "proposal_id", "risk_decision_id"):
            if not str(getattr(self, name)).strip():
                raise ExecutionSafetyError(f"{name} must not be empty")
        if self.execution_mode not in ("paper", "live"):
            raise ExecutionSafetyError("approval execution_mode must be paper or live")
        for name in ("proposal_hash", "risk_hash", "manifest_hash"):
            object.__setattr__(self, name, sha256_field(getattr(self, name), name))
        if not isinstance(self.account_seq, int) or self.account_seq <= 0:
            raise ExecutionSafetyError("approval account_seq must be positive")

        order_ids = tuple(dict.fromkeys(
            str(value).strip() for value in self.allowed_client_order_ids if str(value).strip()
        ))
        # 중복을 조용히 걷어내면 "승인한 주문 수"와 "나갈 주문 수"가 달라진다.
        if not order_ids or len(order_ids) != len(self.allowed_client_order_ids):
            raise ExecutionSafetyError("approval client_order_ids are empty or duplicated")
        object.__setattr__(self, "allowed_client_order_ids", order_ids)

        if self.status not in STATUSES:
            raise ExecutionSafetyError("invalid approval status")
        object.__setattr__(self, "discord_guild_id", snowflake(self.discord_guild_id, "guild_id"))
        object.__setattr__(
            self, "discord_channel_id", snowflake(self.discord_channel_id, "channel_id")
        )
        if self.discord_message_id is not None:
            object.__setattr__(
                self, "discord_message_id", snowflake(self.discord_message_id, "message_id")
            )
        approvers = tuple(dict.fromkeys(
            snowflake(value, "approver_user_id") for value in self.allowed_approver_user_ids
        ))
        if not approvers:
            # 빈 허용 목록은 "아무도 승인할 수 없다"가 아니라 "누구나"로 읽히기 쉽다.
            raise ExecutionSafetyError("Discord approver allowlist is empty")
        object.__setattr__(self, "allowed_approver_user_ids", approvers)

        requested_at = parse_datetime(self.requested_at)
        expires_at = parse_datetime(self.expires_at)
        if expires_at <= requested_at:
            raise ExecutionSafetyError("approval expires_at must be after requested_at")
        object.__setattr__(self, "requested_at", requested_at)
        object.__setattr__(self, "expires_at", expires_at)
        for name in ("decided_at", "consumed_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, parse_datetime(value))
        if self.decided_by_user_id is not None:
            object.__setattr__(
                self, "decided_by_user_id",
                snowflake(self.decided_by_user_id, "decided_by_user_id"),
            )
        if self.decision not in (None, "approved", "rejected"):
            raise ExecutionSafetyError("invalid approval decision")
        self._check_state()

    def _check_state(self) -> None:
        """상태와 결정이 어긋나면 거절한다.

        어긋난 행을 통과시키면 "승인되지 않았는데 승인된 것처럼 보이는" 상태가 생기고,
        그 상태를 만든 경로는 나중에 찾을 수 없다.
        """
        decided_fields = (self.decision, self.decided_at, self.decided_by_user_id, self.consumed_at)
        if self.status == "pending" and any(value is not None for value in decided_fields):
            raise ExecutionSafetyError("pending approval cannot have a decision")
        if self.status in ("approved", "rejected"):
            if (
                self.decision != self.status
                or self.decided_at is None
                or self.decided_by_user_id is None
                or self.consumed_at is not None
                or self.discord_message_id is None
            ):
                raise ExecutionSafetyError("decided approval state is inconsistent")
        if self.status == "expired":
            # 만료에는 두 모양이 있다 — 아무도 안 누른 채 지난 것과, 승인은 됐지만
            # 쓰이기 전에 지난 것. 둘 다 소비되지 않았어야 한다.
            undecided = (
                self.decision is None
                and self.decided_at is None
                and self.decided_by_user_id is None
            )
            approved_before_expiry = (
                self.decision == "approved"
                and self.decided_at is not None
                and self.decided_by_user_id is not None
                and self.discord_message_id is not None
            )
            if self.consumed_at is not None or not (undecided or approved_before_expiry):
                raise ExecutionSafetyError("expired approval state is inconsistent")
        if self.status == "consumed" and (
            self.decision != "approved"
            or self.decided_at is None
            or self.decided_by_user_id is None
            or self.consumed_at is None
            or self.discord_message_id is None
        ):
            raise ExecutionSafetyError("consumed approval state is inconsistent")

    @classmethod
    def create(
        cls,
        *,
        intent_id: str,
        proposal_id: str,
        risk_decision_id: str,
        execution_mode: str,
        proposal_hash: str,
        risk_hash: str,
        manifest_hash: str,
        account_seq: int,
        allowed_client_order_ids: Iterable[str],
        discord_guild_id: str,
        discord_channel_id: str,
        allowed_approver_user_ids: Iterable[str],
        requested_at: datetime | None = None,
        ttl: timedelta = timedelta(minutes=15),
        latest_expiry: datetime | None = None,
    ) -> "ApprovalRequest":
        """`intent` 만료를 넘지 않는 pending 요청을 만든다.

        `latest_expiry`로 자르는 이유: 의도가 끝난 뒤에도 살아 있는 승인은 "승인은
        받았는데 실행할 수 없는" 상태를 만들고, 그것을 사람이 다시 눌러 해결하려 든다.
        """
        now = ensure_aware(requested_at or utc_now())
        if ttl <= timedelta(0) or ttl > MAX_APPROVAL_TTL:
            raise ExecutionSafetyError("approval TTL must be between 0 and 24 hours")
        expires_at = now + ttl
        if latest_expiry is not None:
            expires_at = min(expires_at, parse_datetime(latest_expiry))
        if expires_at <= now:
            raise ExecutionSafetyError("execution intent expires before approval request")
        return cls(
            approval_id=create_approval_id(),
            intent_id=intent_id,
            proposal_id=proposal_id,
            risk_decision_id=risk_decision_id,
            execution_mode=execution_mode,
            proposal_hash=proposal_hash,
            risk_hash=risk_hash,
            manifest_hash=manifest_hash,
            account_seq=account_seq,
            allowed_client_order_ids=tuple(allowed_client_order_ids),
            status="pending",
            discord_guild_id=discord_guild_id,
            discord_channel_id=discord_channel_id,
            discord_message_id=None,
            allowed_approver_user_ids=tuple(allowed_approver_user_ids),
            requested_at=now,
            expires_at=expires_at,
        )

    def as_row(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "intent_id": self.intent_id,
            "proposal_id": self.proposal_id,
            "risk_decision_id": self.risk_decision_id,
            "execution_mode": self.execution_mode,
            "proposal_hash": self.proposal_hash,
            "risk_hash": self.risk_hash,
            "manifest_hash": self.manifest_hash,
            "account_seq": self.account_seq,
            "allowed_client_order_ids": list(self.allowed_client_order_ids),
            "status": self.status,
            "discord_guild_id": self.discord_guild_id,
            "discord_channel_id": self.discord_channel_id,
            "discord_message_id": self.discord_message_id,
            "allowed_approver_user_ids": list(self.allowed_approver_user_ids),
            "requested_at": self.requested_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "decision": self.decision,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decided_by_user_id": self.decided_by_user_id,
            "consumed_at": self.consumed_at.isoformat() if self.consumed_at else None,
        }


@dataclass(frozen=True)
class ApprovalInteraction:
    """Discord 버튼 입력에서 신뢰 경계가 필요로 하는 값만."""

    approval_id: str
    action: str
    expires_epoch: int
    signature: str
    discord_guild_id: str
    discord_channel_id: str
    discord_message_id: str
    discord_user_id: str


class ApprovalSigner:
    """버튼을 그 계획에 묶는다.

    Discord는 버튼이 어느 계획에 붙어 있었는지 알려주지 않는다. 서명이 없으면 버튼
    하나가 "무엇이든 승인"이 되고, 어제 카드의 버튼으로 오늘 주문을 낼 수 있다.
    """

    def __init__(self, secret: str | bytes) -> None:
        raw = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        if len(raw) < 32:
            raise ExecutionSafetyError("approval HMAC secret must be at least 32 bytes")
        self._secret = raw

    @staticmethod
    def _action_code(action: str) -> str:
        if action not in ACTIONS:
            raise ExecutionSafetyError("invalid approval action")
        return "a" if action == "approve" else "r"

    @staticmethod
    def _payload(request: ApprovalRequest, action_code: str, expires_epoch: int) -> bytes:
        """서명 대상. **계획을 결정하는 것이 전부 들어간다.**

        하나라도 빠지면 그 값만 바꿔치기한 재사용이 가능해진다 — 예를 들어 계좌가
        빠지면 같은 버튼으로 다른 계좌에 주문할 수 있다.
        """
        values = (
            "eap1",
            action_code,
            request.approval_id,
            str(expires_epoch),
            request.intent_id,
            request.proposal_id,
            request.risk_decision_id,
            request.execution_mode,
            request.proposal_hash,
            request.risk_hash,
            request.manifest_hash,
            str(request.account_seq),
            ",".join(request.allowed_client_order_ids),
            request.discord_guild_id,
            request.discord_channel_id,
        )
        return "|".join(values).encode("utf-8")

    def custom_id(self, request: ApprovalRequest, action: str) -> str:
        action_code = self._action_code(action)
        expires_epoch = int(ensure_aware(request.expires_at).timestamp())
        digest = hmac.new(
            self._secret, self._payload(request, action_code, expires_epoch), hashlib.sha256
        ).digest()[:16]
        signature = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        custom_id = f"eap1:{action_code}:{request.approval_id}:{expires_epoch}:{signature}"
        if len(custom_id) > MAX_CUSTOM_ID:
            raise ExecutionSafetyError("Discord custom_id exceeds 100 characters")
        return custom_id

    def verify(self, request: ApprovalRequest, interaction: ApprovalInteraction) -> None:
        """이 버튼이 이 계획의 것인가. 아니면 예외."""
        if interaction.approval_id != request.approval_id:
            raise ExecutionSafetyError("Discord approval_id does not match")
        expected = self.custom_id(request, interaction.action)
        actual = (
            f"eap1:{self._action_code(interaction.action)}:{interaction.approval_id}:"
            f"{interaction.expires_epoch}:{interaction.signature}"
        )
        # compare_digest: 길이·내용 비교 시간이 값에 따라 달라지지 않게 한다.
        if not hmac.compare_digest(actual, expected):
            raise ExecutionSafetyError("invalid Discord approval signature")


def parse_button_interaction(payload: Mapping[str, Any]) -> ApprovalInteraction:
    """정확히 **버튼**만 승인으로 받는다.

    이모지 반응·답장·슬래시 명령은 승인이 아니다. 느슨하게 받으면 실수로 누른 반응이
    주문이 된다.
    """
    if payload.get("type") != 3:
        raise ExecutionSafetyError("only Discord message-component interactions are accepted")
    data = payload.get("data")
    if not isinstance(data, Mapping) or data.get("component_type") != 2:
        raise ExecutionSafetyError("only exact Discord button interactions are accepted")
    custom_id = data.get("custom_id")
    if not isinstance(custom_id, str):
        raise ExecutionSafetyError("Discord button has no custom_id")
    match = CUSTOM_ID_RE.fullmatch(custom_id)
    if match is None:
        raise ExecutionSafetyError("invalid Discord approval custom_id")

    member = payload.get("member")
    member_user = member.get("user") if isinstance(member, Mapping) else None
    direct_user = payload.get("user")
    user = member_user if isinstance(member_user, Mapping) else direct_user
    message = payload.get("message")
    if not isinstance(user, Mapping) or not isinstance(message, Mapping):
        raise ExecutionSafetyError("Discord interaction identity is incomplete")
    return ApprovalInteraction(
        approval_id=match.group("approval_id"),
        action="approve" if match.group("action") == "a" else "reject",
        expires_epoch=int(match.group("expires")),
        signature=match.group("signature"),
        discord_guild_id=snowflake(payload.get("guild_id"), "guild_id"),
        discord_channel_id=snowflake(payload.get("channel_id"), "channel_id"),
        discord_message_id=snowflake(message.get("id"), "message_id"),
        discord_user_id=snowflake(user.get("id"), "user_id"),
    )


def approver_allowlist(*values: str) -> tuple[str, ...]:
    """쉼표로 나열된 설정을 중복 없는 승인자 목록으로. 비면 예외."""
    items: list[str] = []
    for value in values:
        items.extend(piece.strip() for piece in value.split(",") if piece.strip())
    parsed = tuple(dict.fromkeys(snowflake(item, "approver_user_id") for item in items))
    if not parsed:
        raise ExecutionSafetyError("Discord approver allowlist is empty")
    return parsed


@dataclass(frozen=True)
class LiveExecutionPermit:
    """소비된 승인 하나가 허용하는 주문 집합. **몇 분짜리다.**"""

    approval_id: str
    intent_id: str
    manifest_hash: str
    account_seq: int
    approved_by_user_id: str
    approval_message_id: str
    issued_at: datetime
    expires_at: datetime
    allowed_client_order_ids: tuple[str, ...]
    grant_status: str = "consumed"

    def __post_init__(self) -> None:
        if not self.approval_id or not self.intent_id:
            raise ExecutionSafetyError("permit approval_id and intent_id are required")
        object.__setattr__(self, "manifest_hash", sha256_field(self.manifest_hash, "manifest_hash"))
        if not isinstance(self.account_seq, int) or self.account_seq <= 0:
            raise ExecutionSafetyError("permit account_seq must be a positive integer")
        if not self.approved_by_user_id or not self.approval_message_id:
            raise ExecutionSafetyError("permit Discord identity is required")
        issued = parse_datetime(self.issued_at)
        expires = parse_datetime(self.expires_at)
        if expires <= issued:
            raise ExecutionSafetyError("permit expires_at must be after issued_at")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)
        if self.grant_status != "consumed":
            # 소비되지 않은 승인으로 permit을 만들면 같은 승인을 여러 번 쓸 수 있다.
            raise ExecutionSafetyError("only an atomically consumed approval may issue a permit")
        if not self.allowed_client_order_ids:
            raise ExecutionSafetyError("permit must authorize at least one client order id")
        if len(set(self.allowed_client_order_ids)) != len(self.allowed_client_order_ids):
            raise ExecutionSafetyError("permit client order ids must be unique")


def issue_live_execution_permit(
    *,
    approval: ApprovalRequest,
    intent_id: str,
    intent_execution_mode: str,
    intent_status: str,
    intent_not_before: datetime,
    intent_expires_at: datetime,
    intent_proposal_id: str,
    intent_risk_decision_id: str,
    handoff_intent_id: str,
    handoff_manifest_hash: str,
    handoff_account_seq: int,
    handoff_client_order_ids: tuple[str, ...],
    account_seq: int,
    now: datetime | None = None,
    ttl_seconds: int = 120,
) -> LiveExecutionPermit:
    """소비된 승인을 짧은 실주문 permit으로 바꾼다.

    **DB를 바꾸지도, 네트워크를 부르지도 않는다.** 부르는 쪽이 먼저 `consume_approval`로
    원자적으로 소비한 행을 넘겨야 한다.

    인자를 dataclass가 아니라 낱개로 받는 이유: 실행 계층이 판단 계층의 자료구조를
    import하지 않기 위해서다. 필요한 사실만 값으로 건네받는다.
    """
    if not isinstance(account_seq, int) or account_seq <= 0:
        raise ExecutionSafetyError("live permit account_seq must be positive")
    if not isinstance(ttl_seconds, int) or not (
        MIN_PERMIT_TTL_SECONDS <= ttl_seconds <= MAX_PERMIT_TTL_SECONDS
    ):
        raise ExecutionSafetyError("live permit TTL must be between 1 and 300 seconds")
    current = ensure_aware(now or utc_now())

    if approval.status != "consumed" or approval.decision != "approved":
        raise ExecutionSafetyError("live permit requires an atomically consumed approval")
    if approval.execution_mode != "live" or intent_execution_mode != "live":
        # 종이 승인으로 실주문 permit을 만들 수 있으면 승인 화면의 의미가 사라진다.
        raise ExecutionSafetyError("paper approval can never issue a live permit")
    if intent_status != "approved":
        raise ExecutionSafetyError("live intent is no longer approved")
    if (
        approval.intent_id != intent_id
        or approval.proposal_id != intent_proposal_id
        or approval.risk_decision_id != intent_risk_decision_id
        or handoff_intent_id != intent_id
    ):
        raise ExecutionSafetyError("approval, intent, and handoff identity do not match")
    if approval.manifest_hash != sha256_field(handoff_manifest_hash, "manifest_hash"):
        raise ExecutionSafetyError("approved plan hash does not match the handoff")
    if handoff_account_seq != account_seq or approval.account_seq != account_seq:
        raise ExecutionSafetyError("approved plan is bound to a different Toss account")

    consumed_at = approval.consumed_at
    if consumed_at is None:
        raise ExecutionSafetyError("consumed approval must carry consumed_at")
    if current < ensure_aware(intent_not_before) or current < ensure_aware(consumed_at):
        raise ExecutionSafetyError("live permit cannot be issued before its source state")
    # permit은 승인·의도 중 먼저 끝나는 것보다 오래 살 수 없다.
    expires_at = min(
        current + timedelta(seconds=ttl_seconds),
        ensure_aware(approval.expires_at),
        ensure_aware(intent_expires_at),
    )
    if expires_at <= current:
        raise ExecutionSafetyError("consumed approval or live intent has expired")

    order_ids = tuple(handoff_client_order_ids)
    if not order_ids or len(order_ids) != len(set(order_ids)):
        raise ExecutionSafetyError("live handoff client_order_ids are empty or duplicated")
    if order_ids != approval.allowed_client_order_ids:
        raise ExecutionSafetyError("approval does not cover the handoff client_order_ids")

    return LiveExecutionPermit(
        approval_id=approval.approval_id,
        intent_id=intent_id,
        manifest_hash=approval.manifest_hash,
        account_seq=account_seq,
        approved_by_user_id=str(approval.decided_by_user_id),
        approval_message_id=str(approval.discord_message_id),
        issued_at=current,
        expires_at=expires_at,
        allowed_client_order_ids=order_ids,
    )


__all__ = [
    "ACTIONS",
    "APPROVAL_ID_RE",
    "ApprovalInteraction",
    "ApprovalRequest",
    "ApprovalSigner",
    "CUSTOM_ID_RE",
    "HASH_RE",
    "LiveExecutionPermit",
    "MAX_APPROVAL_TTL",
    "MAX_CUSTOM_ID",
    "MAX_PERMIT_TTL_SECONDS",
    "MIN_PERMIT_TTL_SECONDS",
    "SNOWFLAKE_RE",
    "STATUSES",
    "approver_allowlist",
    "create_approval_id",
    "issue_live_execution_permit",
    "parse_button_interaction",
    "sha256_field",
    "snowflake",
]
