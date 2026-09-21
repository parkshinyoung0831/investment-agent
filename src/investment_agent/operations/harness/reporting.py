"""구조화 로그와 Discord 운영 webhook 사이의 좁은 adapter."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from investment_agent.platform.serialization import canonical_json
from investment_agent.platform.cli.runtime import notify_ops
from investment_agent.platform.logging import get_logger
from investment_agent.operations.harness.sanitize import sanitized

# 같은 사건을 다시 webhook으로 보내기까지의 최소 간격.
# 주기가 60초인 job(`earnings_watch`·`econ_release_watch`·`toss_reconciliation`·
# `my_portfolio_follow`)이 영구 원인으로 실패하면 하루 약 1,400건이 나가고, Discord
# webhook 한도에 걸린 429는 `notify_ops`가 삼킨다 — 그러면 **다른 실패 알림이 그 홍수에
# 묻힌다**(감사 OP2-15). 알림 본류에는 원장이 있는데 ops 경보에만 없던 계약이다.
OPS_ALERT_REPEAT_SECONDS = 30 * 60
# 억제 키 개수 상한. 키가 무한히 늘지 않게 오래된 것부터 버린다.
_MAX_TRACKED_KEYS = 512


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
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.logger = logger or get_logger(__name__)
        self.alerts = alerts or NoopOpsAlert()
        self._monotonic = monotonic or time.monotonic
        # 사건 키 → (마지막 발송 시각, 그 뒤 억제한 건수)
        self._alerted: dict[str, tuple[float, int]] = {}

    def event(self, event_type: str, **fields: Any) -> None:
        payload = sanitized({"event": event_type, **fields})
        self.logger.info("harness_event=%s", canonical_json(payload))

    def error(self, event_type: str, **fields: Any) -> None:
        """로그는 매번, webhook은 같은 사건당 `OPS_ALERT_REPEAT_SECONDS`에 한 번.

        억제된 동안에도 로그는 남으므로 사실이 사라지지 않는다. 다시 보낼 때는 그 사이
        억제한 건수를 함께 실어, 조용해진 것과 반복된 것을 구분할 수 있게 한다.
        """
        payload = sanitized({"event": event_type, **fields})
        self.logger.error("harness_event=%s", canonical_json(payload))
        key = self._alert_key(event_type, fields)
        now = self._monotonic()
        last, suppressed = self._alerted.get(key, (None, 0))
        if last is not None and now - last < OPS_ALERT_REPEAT_SECONDS:
            self._alerted[key] = (last, suppressed + 1)
            return
        if suppressed:
            payload = {**payload, "suppressed_repeats": suppressed}
        self._alerted[key] = (now, 0)
        if len(self._alerted) > _MAX_TRACKED_KEYS:
            oldest = min(self._alerted, key=lambda name: self._alerted[name][0])
            self._alerted.pop(oldest, None)
        self.alerts.send(payload)

    @staticmethod
    def _alert_key(event_type: str, fields: Mapping[str, Any]) -> str:
        """같은 원인을 한 사건으로 묶는 키.

        job·stage·오류 종류까지 넣어야 "다른 job의 같은 오류"가 함께 억제되지 않는다.
        시각·시도 횟수처럼 매번 달라지는 값은 넣지 않는다 — 넣으면 억제가 무력해진다.
        """
        parts = [event_type]
        for name in ("job_id", "stage_id", "error_type", "error", "reason", "workflow"):
            value = fields.get(name)
            if value is not None:
                parts.append(f"{name}={value}")
        return "|".join(parts)
