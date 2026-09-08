"""DB의 수동 제어 상태를 env controls와 AND 결합한다."""
from __future__ import annotations

from dataclasses import dataclass

from investment_agent.platform.serialization import parse_datetime
from investment_agent.execution.contracts import ExecutionSafetyError


@dataclass(frozen=True)
class DurableControlState:
    scope: str
    kill_switch_on: bool
    durable_lockdown_on: bool
    live_enabled: bool
    live_autonomy_enabled: bool
    version: int
    reason: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict) -> "DurableControlState":
        state = cls(
            scope=str(row["scope"]),
            kill_switch_on=row.get("kill_switch_on") is not False,
            durable_lockdown_on=row.get("durable_lockdown_on") is not False,
            live_enabled=row.get("live_enabled") is True,
            live_autonomy_enabled=row.get("live_autonomy_enabled") is True,
            version=int(row["version"]),
            reason=str(row.get("reason") or ""),
            updated_at=str(row["updated_at"]),
        )
        parse_datetime(state.updated_at)
        if state.live_autonomy_enabled and not state.live_enabled:
            raise ExecutionSafetyError("durable control state is internally inconsistent")
        return state

    def assert_live_manual_allowed(self) -> None:
        if self.kill_switch_on or self.durable_lockdown_on or not self.live_enabled:
            raise ExecutionSafetyError(f"durable database control blocks live execution: {self.reason}")

    def assert_live_autonomous_allowed(self) -> None:
        self.assert_live_manual_allowed()
        if not self.live_autonomy_enabled:
            raise ExecutionSafetyError("durable database control blocks autonomous live execution")


__all__ = ["DurableControlState"]
