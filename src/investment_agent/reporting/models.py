"""화면과 알림의 조회 상태를 보존하는 공통 결과 모델."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal


DataStatus = Literal["ok", "empty", "unconfigured", "offline", "blocked", "error"]

_STATUSES: frozenset[str] = frozenset(
    {"ok", "empty", "unconfigured", "offline", "blocked", "error"}
)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|authorization|password)\b\s*[:=]\s*[^\s,;]+"
)
_LONG_SECRET_RE = re.compile(r"\b[A-Za-z0-9_\-./+=]{40,}\b")



def sanitize_message(value: object, *, fallback: str = "요청을 처리하지 못했습니다.") -> str:
    """오류 메시지에서 URL·자격증명처럼 노출 위험이 있는 문자열을 제거한다."""

    text = " ".join(str(value or "").split())
    if not text:
        text = fallback
    text = _URL_RE.sub("[URL 숨김]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[숨김]", text)
    text = _LONG_SECRET_RE.sub("[민감값 숨김]", text)
    return text[:400]


def public_exception_message(prefix: str, error: BaseException) -> str:
    """예외 본문 대신 안전한 오류 유형만 사용자 메시지에 포함한다."""

    return sanitize_message(f"{prefix} ({type(error).__name__})")


def normalize_observed_at(value: object | None) -> str | None:
    """날짜·시각을 직렬화 가능한 ISO 문자열로 정규화한다."""

    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        current = value
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return sanitize_message(value, fallback="") or None


@dataclass(frozen=True)
class DataResult:
    """빈 결과와 연결 실패를 섞지 않는 대시보드 로더 반환값."""

    status: DataStatus
    rows: list[dict[str, Any]] = field(default_factory=list)
    value: Any = None
    source: str = ""
    observed_at: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"지원하지 않는 데이터 상태입니다: {self.status}")
        object.__setattr__(self, "rows", [dict(row) for row in self.rows])
        object.__setattr__(self, "source", sanitize_message(self.source, fallback=""))
        object.__setattr__(self, "observed_at", normalize_observed_at(self.observed_at))
        if self.message is not None:
            object.__setattr__(self, "message", sanitize_message(self.message))

    @property
    def available(self) -> bool:
        """실제로 표시할 데이터가 준비된 결과인지 반환한다."""

        return self.status == "ok"

    @classmethod
    def ok(
        cls,
        *,
        rows: list[dict[str, Any]] | None = None,
        value: Any = None,
        source: str,
        observed_at: object | None = None,
        message: str | None = None,
    ) -> "DataResult":
        return cls(
            status="ok",
            rows=rows or [],
            value=value,
            source=source,
            observed_at=normalize_observed_at(observed_at),
            message=message,
        )

    @classmethod
    def empty(
        cls,
        *,
        source: str,
        rows: list[dict[str, Any]] | None = None,
        value: Any = None,
        observed_at: object | None = None,
        message: str = "조회는 성공했지만 표시할 데이터가 없습니다.",
    ) -> "DataResult":
        return cls(
            status="empty",
            rows=rows or [],
            value=value,
            source=source,
            observed_at=normalize_observed_at(observed_at),
            message=message,
        )

    @classmethod
    def unconfigured(
        cls,
        *,
        source: str,
        rows: list[dict[str, Any]] | None = None,
        value: Any = None,
        observed_at: object | None = None,
        message: str = "필수 연결 설정이 없습니다.",
    ) -> "DataResult":
        return cls(
            status="unconfigured",
            rows=rows or [],
            value=value,
            source=source,
            observed_at=normalize_observed_at(observed_at),
            message=message,
        )

    @classmethod
    def offline(
        cls,
        *,
        source: str,
        rows: list[dict[str, Any]] | None = None,
        value: Any = None,
        observed_at: object | None = None,
        message: str = "오프라인 모드에서 네트워크 조회를 차단했습니다.",
    ) -> "DataResult":
        return cls(
            status="offline",
            rows=rows or [],
            value=value,
            source=source,
            observed_at=normalize_observed_at(observed_at),
            message=message,
        )

    @classmethod
    def blocked(
        cls,
        *,
        source: str,
        message: str,
        rows: list[dict[str, Any]] | None = None,
        value: Any = None,
        observed_at: object | None = None,
    ) -> "DataResult":
        return cls(
            status="blocked",
            rows=rows or [],
            value=value,
            source=source,
            observed_at=normalize_observed_at(observed_at),
            message=message,
        )

    @classmethod
    def error(
        cls,
        *,
        source: str,
        message: str,
        rows: list[dict[str, Any]] | None = None,
        observed_at: object | None = None,
        value: Any = None,
    ) -> "DataResult":
        return cls(
            status="error",
            rows=rows or [],
            source=source,
            observed_at=normalize_observed_at(observed_at),
            message=message,
            value=value,
        )

