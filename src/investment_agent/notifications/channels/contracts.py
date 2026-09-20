"""알림 발행 엔진과 전송 어댑터가 공유하는 최소 계약."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# 현재 전송 어댑터의 nonce 상한. 엔진도 같은 길이를 생성해야 한다.
NONCE_MAX_LENGTH = 25


class DeliveryRejected(RuntimeError):
    """전송되지 않았음이 명확한 응답. 재시도 가능한 거절만 다시 예약한다."""

    def __init__(self, reason: str, *, is_retryable: bool = False, retry_after: float = 60) -> None:
        super().__init__(reason)
        self.is_retryable = is_retryable
        self.retry_after = retry_after


class DeliveryUnknown(RuntimeError):
    """전달 여부 불명. 자동 재전송하면 같은 알림이 두 번 나갈 수 있다."""


@dataclass(frozen=True)
class ForumThread:
    """포럼에서 알림이 쌓일 스레드. key가 정체성이고 name은 생성 시에만 쓴다."""

    key: str
    name: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Delivery:
    """보낸 메시지가 사는 곳. 수정하려면 두 ID가 모두 필요하다."""

    location_id: str
    message_id: str
    thread_id: str | None = None


class NotificationChannel(Protocol):
    def deliver(
        self, *, target: str, message: dict[str, Any], attachment_path: str | None = None,
        thread: ForumThread | None = None, known_thread_id: str | None = None,
        nonce: str | None = None,
    ) -> Delivery: ...

    def edit(
        self, *, location_id: str, message_id: str, message: dict[str, Any],
        attachment_path: str | None = None,
    ) -> Delivery: ...
