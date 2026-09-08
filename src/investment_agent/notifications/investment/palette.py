"""자동매매 보고서 embed 색 토큰 — DESIGN-system.md의 화면 색 SSOT.

embed는 왼쪽 세로 스트라이프 하나만 색을 갖는다. 거래 시맨틱 색을 배경으로 칠하지
않는다는 규칙은 그대로 지킨다 — 본문은 Discord 기본 배경이다.
"""
from __future__ import annotations

# DESIGN-system.md의 semantic up/down. 텍스트와 이 스트라이프에만 쓴다.
SEMANTIC_UP = "#05b169"
SEMANTIC_DOWN = "#cf202f"
# 1차 액션 색. 방향이 없는 정보 카드에만 쓴다 — voltage를 하나로 유지한다.
PRIMARY = "#3182f6"


def _to_int(value: str) -> int:
    """Discord embed는 색을 정수로 받는다. hex 문자열이 SSOT다."""
    return int(value.lstrip("#"), 16)


COLOR_APPROVED = _to_int(SEMANTIC_UP)
COLOR_REJECTED = _to_int(SEMANTIC_DOWN)
COLOR_INFO = _to_int(PRIMARY)

__all__ = [
    "COLOR_APPROVED",
    "COLOR_INFO",
    "COLOR_REJECTED",
    "PRIMARY",
    "SEMANTIC_DOWN",
    "SEMANTIC_UP",
]
