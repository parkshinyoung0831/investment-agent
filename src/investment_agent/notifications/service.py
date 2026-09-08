"""outbox → 전송 → delivery 기록. 상류 계산과 분리된 디스패처."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any

from investment_agent.notifications.channels.discord import DeliveryRejected, validate_message
from investment_agent.notifications.outbox import Outbox
from investment_agent.platform.logging import get_logger
from investment_agent.reporting.models import public_exception_message

log = get_logger(__name__)


@dataclass(frozen=True)
class DispatchResult:
    """상류 성공을 가리지 않고 알림 결과만 반환한다."""

    status: str
    producer: str = ""
    notification_key: str = ""
    message_id: str | None = None
    reason: str | None = None


class NotificationService:
    """DB·시계·전송 어댑터를 주입하고 설정은 직접 읽지 않는다."""

    def __init__(self, outbox: Outbox, channel: Any, *, clock: Callable[[], datetime],
                 max_attempts: int = 3, retry_after: float = 60) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if not math.isfinite(retry_after) or retry_after < 0:
            raise ValueError("retry_after must be finite and nonnegative")
        self._outbox, self._channel, self._clock = outbox, channel, clock
        self._max_attempts, self._retry_after = max_attempts, retry_after

    def enqueue(self, *, producer: str, notification_key: str, kind: str,
                target: str, message: dict[str, Any], entity_key: str | None = None,
                period_end: str | None = None,
                attachment_path: str | None = None,
                thread_name: str | None = None,
                thread_tags: tuple[str, ...] = ()) -> DispatchResult:
        """전송 없이 스냅샷만 보관한다. 실패를 명시적으로 반환하고 상류 예외로 올리지 않는다."""
        try:
            won = self._outbox.enqueue(
                producer=producer, notification_key=notification_key, kind=kind,
                target=target, message=validate_message(message), entity_key=entity_key,
                period_end=period_end, attachment_path=attachment_path,
                thread_name=thread_name, thread_tags=thread_tags, now=self._clock(),
            )
            return DispatchResult("enqueued" if won else "duplicate", producer, notification_key)
        except Exception as exc:
            reason = public_exception_message("알림 저장 실패", exc)
            log.warning("notification_enqueue_failed: %s", reason)
            return DispatchResult("error", producer, notification_key, reason=reason)

    def dispatch(self, row: dict[str, Any]) -> DispatchResult:
        """선점 실패면 전송하지 않는다. 보낸 뒤 기록 실패도 자동 재전송하지 않는다."""
        producer, key = row["producer"], row["notification_key"]
        try:
            attempt = self._outbox.claim(row, now=self._clock(), max_attempts=self._max_attempts)
        except Exception as exc:
            return DispatchResult("error", producer, key, reason=public_exception_message("선점 실패", exc))
        if attempt is None:
            return DispatchResult("skipped", producer, key)
        status, reason, message_id = "sent", None, None
        retry_after = self._retry_after
        try:
            payload = attempt.row["payload"]
            if payload["channel"] != "discord":
                raise DeliveryRejected("unsupported_channel")
            attachment_path = payload.get("attachment_path")
            thread_kwargs: dict[str, Any] = {}
            if payload.get("thread_name"):
                thread_kwargs["thread_name"] = payload["thread_name"]
                if payload.get("thread_tags"):
                    thread_kwargs["thread_tags"] = tuple(payload["thread_tags"])
            if attachment_path is not None:
                message = payload["message"]
                if set(message) - {"content", "embeds", "allowed_mentions"}:
                    raise DeliveryRejected("attachment_message_unsupported")
                file_kwargs = {
                    "target": payload["target"],
                    "path": attachment_path,
                    "content": message.get("content", ""),
                }
                if message.get("embeds"):
                    file_kwargs["embeds"] = message["embeds"]
                message_id = self._channel.send_file(**file_kwargs, **thread_kwargs)
            else:
                message_id = self._channel.send(
                    target=payload["target"], message=payload["message"], **thread_kwargs
                )
        except DeliveryRejected as exc:
            retry_after = max(retry_after, exc.retry_after)
            status = "failed" if exc.is_retryable and attempt.row["attempt_count"] < self._max_attempts else "abandoned"
            # 거절 사유는 어댑터가 고정 코드만 제공하며 임의 예외 본문을 저장하지 않는다.
            reason = public_exception_message("전송 거절", exc)
        except Exception as exc:
            status = "unknown"
            reason = public_exception_message("전달 여부 불명 — 자동 재전송 보류", exc)
        try:
            self._outbox.record(attempt, status=status, now=self._clock(), failure_reason=reason,
                                retry_after=retry_after)
        except Exception as exc:
            reason = public_exception_message("전송 결과 기록 실패 — 재전송 보류", exc)
            log.warning("notification_record_failed: %s", reason)
            return DispatchResult("error", producer, key, message_id=message_id, reason=reason)
        return DispatchResult(status, producer, key, message_id=message_id, reason=reason)

    def run_pending(self) -> list[DispatchResult]:
        try:
            rows = self._outbox.ready(now=self._clock())
        except Exception as exc:
            return [DispatchResult("error", reason=public_exception_message("알림 조회 실패", exc))]
        return [self.dispatch(row) for row in rows]
