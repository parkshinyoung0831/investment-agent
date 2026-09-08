"""Broker에 전달하기 전 주문 계획 계약."""
from __future__ import annotations

class ExecutionSafetyError(RuntimeError):
    """주문을 만들지 않고 즉시 중단해야 하는 안전 오류."""


__all__ = ["ExecutionSafetyError"]
