"""로컬 운영 화면이 공유하는 디자인 시스템 시맨틱 색."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpsPalette:
    """운영 제어센터의 다크 테마 색 역할."""

    canvas: str
    surface: str
    surface_subtle: str
    border: str
    primary: str
    text: str
    secondary_text: str
    muted_text: str
    danger: str


CONTROL_CENTER_PALETTE = OpsPalette(
    canvas="#101318",
    surface="#171B22",
    surface_subtle="#202630",
    border="#333D4B",
    primary="#1B64DA",
    text="#F2F4F6",
    secondary_text="#B0B8C1",
    muted_text="#8B95A1",
    danger="#D22030",
)


# Discord embed는 정수 색 값을 요구한다. DESIGN-system.md의 상태 토큰을 그대로 쓰고,
# 상승·하락 색과 운영 심각도 색을 섞지 않는다.
STATUS_INFO = 0x1B64DA
STATUS_WARNING = 0xB54708
STATUS_DANGER = 0xD22030


__all__ = [
    "CONTROL_CENTER_PALETTE",
    "OpsPalette",
    "STATUS_DANGER",
    "STATUS_INFO",
    "STATUS_WARNING",
]
