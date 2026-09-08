"""뉴스 provider가 data 계층에서 반환하는 결과 계약."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


NewsStatus = Literal["ok", "empty", "offline", "blocked", "error"]


@dataclass(frozen=True)
class NewsResult:
    """provider 호출 결과와 실패 원인을 data 계층 안에서 보존한다."""

    status: NewsStatus
    rows: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""
    observed_at: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"ok", "empty", "offline", "blocked", "error"}:
            raise ValueError(f"지원하지 않는 뉴스 상태입니다: {self.status}")
        object.__setattr__(self, "rows", [dict(row) for row in self.rows])

    @property
    def available(self) -> bool:
        """표시할 뉴스가 준비된 결과인지 반환한다."""

        return self.status == "ok"

    @classmethod
    def ok(
        cls,
        *,
        rows: list[dict[str, Any]] | None = None,
        source: str,
        observed_at: str | None = None,
        message: str | None = None,
    ) -> "NewsResult":
        return cls("ok", rows or [], source, observed_at, message)

    @classmethod
    def empty(
        cls,
        *,
        source: str,
        observed_at: str | None = None,
        message: str = "조회는 성공했지만 표시할 뉴스가 없습니다.",
    ) -> "NewsResult":
        return cls("empty", [], source, observed_at, message)

    @classmethod
    def offline(
        cls,
        *,
        source: str,
        message: str = "오프라인 모드에서 네트워크 조회를 차단했습니다.",
    ) -> "NewsResult":
        return cls("offline", [], source, None, message)

    @classmethod
    def blocked(cls, *, source: str, message: str) -> "NewsResult":
        return cls("blocked", [], source, None, message)

    @classmethod
    def error(cls, *, source: str, message: str) -> "NewsResult":
        return cls("error", [], source, None, message)


__all__ = ["NewsResult", "NewsStatus"]


class SocialCredentialsMissing(RuntimeError):
    """Reddit 자격증명이 없다. 오류가 아니라 아직 켜지지 않은 상태다."""


class SocialQuotaExhausted(RuntimeError):
    """오늘 provider 한도를 다 썼다.

    수집 유스케이스와 reddit 어댑터가 함께 쓰는 계약이라 둘 중 어느 계층에도
    두지 않는다. application에 두면 infrastructure가 위를 import하게 되고,
    infrastructure에 두면 application이 어댑터를 알게 된다.
    """
