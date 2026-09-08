"""상태·로그·설치 미리보기에 비밀값이 섞이지 않게 정리한다."""
from __future__ import annotations

from typing import Any, Mapping

_SENSITIVE_FRAGMENTS = (
    "authorization", "credential", "password", "secret", "token", "webhook", "api_key",
)


def sanitized(value: Any) -> Any:
    """민감한 key의 값은 타입과 무관하게 고정 문자열로 바꾼다."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            label = str(key)
            lowered = label.lower()
            result[label] = (
                "[REDACTED]"
                if any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)
                else sanitized(item)
            )
        return result
    if isinstance(value, (list, tuple)):
        return [sanitized(item) for item in value]
    return value
