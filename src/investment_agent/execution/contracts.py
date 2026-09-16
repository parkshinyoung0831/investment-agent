"""Broker에 전달하기 전 주문 계획 계약."""
from __future__ import annotations

class ExecutionSafetyError(RuntimeError):
    """주문을 만들지 않고 즉시 중단해야 하는 안전 오류."""


def __getattr__(name: str) -> object:
    """안전 게이트 초기화와 orders 계약 재노출이 순환하지 않게 지연해서 연다."""
    if name == "ExecutionLimits":
        from investment_agent.execution.orders.planning import ExecutionLimits

        return ExecutionLimits
    if name == "AccountSnapshot":
        from investment_agent.execution.orders.snapshots import AccountSnapshot

        return AccountSnapshot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AccountSnapshot", "ExecutionLimits", "ExecutionSafetyError"]
