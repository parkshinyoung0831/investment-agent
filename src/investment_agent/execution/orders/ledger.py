"""주문 시도의 변경 불가능한 원장.

## 네트워크 호출 **전에** 한 줄을 예약한다

주문을 보낸 뒤 기록하면, 보내는 도중에 프로세스가 죽었을 때 그 주문의 흔적이 없다.
다음 실행은 "안 보냈다"고 읽고 다시 보낸다 — 그러면 같은 주문이 두 번 나간다.

그래서 순서를 뒤집는다. **먼저 예약하고, 그다음 보낸다.** 예약이 이미 있으면 그것은
"보내도 된다"가 아니라 "결과를 확인해야 한다"는 뜻이다.

## attempt_id는 계산되는 값이다

`(client_order_id, operation, payload_hash)`의 지문이다. 같은 주문을 같은 내용으로 다시
시도하면 같은 id가 나오므로, 저장소가 두 번째를 거부한다. 무작위 id였다면 재시도가
전부 새 시도로 기록되고 중복이 보이지 않는다.

## payload가 바뀌면 다른 시도다

수량이나 가격이 달라진 재전송은 같은 주문이 아니다. `payload_hash`가 id에 들어가므로
그 차이가 id에 드러난다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping

from investment_agent.execution.safety.control import ExecutionSafetyError
from investment_agent.platform.clock import ensure_aware, utc_now
from investment_agent.platform.serialization import canonical_json, parse_datetime

ATTEMPT_ID_RE = re.compile(r"^attempt_[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

OPERATIONS = ("create", "modify", "cancel")

# 시도가 지날 수 있는 상태. `outcome_unknown`이 있는 것이 핵심이다 — 보냈는지 아닌지
# 모르는 상태를 표현하지 못하면 그것을 실패로 적게 되고, 실패로 적으면 다시 보낸다.
EVENT_STATUSES = (
    "reserved", "submitting", "submitted", "rejected", "outcome_unknown",
    "reconciling", "reconciled_submitted", "reconciled_rejected",
    "partially_filled", "filled", "cancelled", "replacement_created", "failed",
)


def payload_digest(payload: Mapping[str, Any]) -> str:
    """요청 내용의 지문. canonical JSON이라 키 순서가 달라도 같은 값이다."""
    return hashlib.sha256(canonical_json(dict(payload)).encode("utf-8")).hexdigest()


def make_attempt_id(*, client_order_id: str, operation: str, payload_hash: str) -> str:
    """같은 주문·같은 작업·같은 내용이면 같은 id."""
    identity = {
        "client_order_id": client_order_id,
        "operation": operation,
        "payload_hash": payload_hash,
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:32]
    return f"attempt_{digest}"


@dataclass(frozen=True)
class OrderAttempt:
    """네트워크 호출 전에 한 번만 예약하는 시도. 만든 뒤에는 바뀌지 않는다."""

    attempt_id: str
    client_order_id: str
    intent_id: str
    approval_id: str
    operation: str
    payload_hash: str
    manifest_hash: str
    account_seq: int
    request_payload: dict[str, Any]
    broker_order_id: str | None = None
    replaces_client_order_id: str | None = None
    reserved_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not ATTEMPT_ID_RE.fullmatch(self.attempt_id):
            raise ExecutionSafetyError("invalid order attempt_id")
        for name in ("client_order_id", "intent_id", "approval_id"):
            if not str(getattr(self, name)).strip():
                raise ExecutionSafetyError(f"order attempt {name} is required")
        if self.operation not in OPERATIONS:
            raise ExecutionSafetyError("invalid order attempt operation")
        for name in ("payload_hash", "manifest_hash"):
            if not SHA256_RE.fullmatch(str(getattr(self, name))):
                raise ExecutionSafetyError(f"order attempt {name} must be sha256")
        if not isinstance(self.account_seq, int) or self.account_seq <= 0:
            raise ExecutionSafetyError("order attempt account_seq must be positive")
        if not isinstance(self.request_payload, dict):
            raise ExecutionSafetyError("order attempt request_payload must be an object")
        if payload_digest(self.request_payload) != self.payload_hash:
            raise ExecutionSafetyError("order attempt payload hash does not match request")
        try:
            object.__setattr__(self, "reserved_at", parse_datetime(self.reserved_at))
        except ValueError as exc:
            raise ExecutionSafetyError("order attempt reserved_at must include a timezone") from exc
        # id가 내용에서 나오는지 다시 확인한다. 손으로 만든 시도가 섞이면 멱등성이 깨진다.
        expected = make_attempt_id(
            client_order_id=self.client_order_id,
            operation=self.operation,
            payload_hash=self.payload_hash,
        )
        if self.attempt_id != expected:
            raise ExecutionSafetyError("order attempt_id does not match its immutable payload")

    @classmethod
    def create(
        cls,
        *,
        client_order_id: str,
        intent_id: str,
        approval_id: str,
        operation: str,
        request_payload: Mapping[str, Any],
        manifest_hash: str,
        account_seq: int,
        broker_order_id: str | None = None,
        replaces_client_order_id: str | None = None,
        reserved_at: datetime | None = None,
    ) -> "OrderAttempt":
        payload = dict(request_payload)
        digest = payload_digest(payload)
        return cls(
            attempt_id=make_attempt_id(
                client_order_id=client_order_id, operation=operation, payload_hash=digest
            ),
            client_order_id=client_order_id,
            intent_id=intent_id,
            approval_id=approval_id,
            operation=operation,
            payload_hash=digest,
            manifest_hash=manifest_hash,
            account_seq=account_seq,
            request_payload=payload,
            broker_order_id=broker_order_id,
            replaces_client_order_id=replaces_client_order_id,
            reserved_at=reserved_at or utc_now(),
        )

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["reserved_at"] = ensure_aware(self.reserved_at).isoformat()
        return row


@dataclass(frozen=True)
class OrderAttemptReservation:
    """예약 결과. **이미 있었는지**가 여기서 유일하게 중요한 정보다."""

    attempt: OrderAttempt
    reserved_new: bool

    def require_new(self) -> OrderAttempt:
        """새로 예약한 것만 통과시킨다.

        기존 예약을 재전송 허가로 오인하면 같은 주문이 두 번 나간다. 이미 있으면
        보낼 것이 아니라 **결과를 확인할** 차례다.
        """
        if not self.reserved_new:
            raise ExecutionSafetyError(
                "client_order_id was already reserved; reconcile instead of resubmitting"
            )
        return self.attempt


@dataclass(frozen=True)
class OrderAttemptEvent:
    """시도에 붙는 사건 하나. 상태는 덮어쓰지 않고 쌓는다."""

    event_id: int
    attempt_id: str
    status: str
    broker_order_id: str | None
    raw_status: str | None
    raw_response: dict[str, Any]
    occurred_at: datetime

    def __post_init__(self) -> None:
        if self.event_id <= 0 or not ATTEMPT_ID_RE.fullmatch(self.attempt_id):
            raise ExecutionSafetyError("invalid order attempt event identity")
        if self.status not in EVENT_STATUSES:
            raise ExecutionSafetyError("invalid order attempt event status")
        if not isinstance(self.raw_response, dict):
            raise ExecutionSafetyError("order attempt raw_response must be an object")
        try:
            object.__setattr__(self, "occurred_at", parse_datetime(self.occurred_at))
        except ValueError as exc:
            raise ExecutionSafetyError("order attempt event occurred_at must include a timezone") from exc

    @property
    def needs_reconciliation(self) -> bool:
        """사람이나 재동기화가 확인해야 하는 상태인가.

        `outcome_unknown`을 실패로 다루면 다시 보내게 되고, 그것이 중복 체결의
        가장 흔한 경로다.
        """
        return self.status in {"outcome_unknown", "reconciling"}


__all__ = [
    "ATTEMPT_ID_RE",
    "EVENT_STATUSES",
    "OPERATIONS",
    "OrderAttempt",
    "OrderAttemptEvent",
    "OrderAttemptReservation",
    "make_attempt_id",
    "payload_digest",
]
