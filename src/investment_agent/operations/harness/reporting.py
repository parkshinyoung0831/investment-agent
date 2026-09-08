"""구조화 로그와 Discord 운영 webhook 사이의 좁은 adapter."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from investment_agent.platform.serialization import canonical_json
from investment_agent.operations.runtime import notify_ops
from investment_agent.platform.logging import get_logger
from investment_agent.operations.harness.sanitize import sanitized


class OpsAlertAdapter(Protocol):
    def send(self, event: Mapping[str, Any]) -> bool: ...


_SUPPRESSED_WEBHOOK_EVENTS = {
    "duplicate_process",
    "approval_listener_duplicate_process",
    "duplicate_process_skipped",
}


@dataclass
class DiscordOpsAlert:
    """실패 알림만 운영 webhook으로 전달한다.

    하네스는 로컬에서 돈다 — 목적지는 `#로컬-실패`다. 어느 webhook을 쓸지는
    `notify_ops`가 실행된 곳을 보고 정하므로 여기서 고르지 않는다.
    """

    logger: Any

    def send(self, event: Mapping[str, Any]) -> bool:
        event_name = event.get("event")
        if event_name in _SUPPRESSED_WEBHOOK_EVENTS:
            return False
        safe = sanitized(event)
        return notify_ops(
            f"investment harness alert: {canonical_json(safe)}",
            logger=self.logger,
        )


class NoopOpsAlert:
    def send(self, event: Mapping[str, Any]) -> bool:
        return False


class HarnessReporter:
    def __init__(
        self,
        *,
        logger: Any | None = None,
        alerts: OpsAlertAdapter | None = None,
    ) -> None:
        self.logger = logger or get_logger(__name__)
        self.alerts = alerts or NoopOpsAlert()

    def event(self, event_type: str, **fields: Any) -> None:
        payload = sanitized({"event": event_type, **fields})
        self.logger.info("harness_event=%s", canonical_json(payload))

    def error(self, event_type: str, **fields: Any) -> None:
        payload = sanitized({"event": event_type, **fields})
        self.logger.error("harness_event=%s", canonical_json(payload))
        self.alerts.send(payload)
