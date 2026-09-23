"""자동매매 보고서 embed 색 토큰 — DESIGN-system.md의 화면 색 SSOT.

embed는 왼쪽 세로 rail 하나만 색을 갖는다(§2.4). rail은 **중성색이 기본**이고 시스템 경고에만 `status.*`를
쓴다. 방향색(상승·하락)을 rail에 쓰지 않고, 승인·거절이나 매수·매도를 초록·빨강으로 바꿔 칠하지 않는다 —
매수가 좋은 일이고 거절이 나쁜 일이라고 색으로 단정하지 않는다(§3.4).
"""
from __future__ import annotations

# §5.2 grey.500 — 방향도 상태도 없는 보고 카드의 rail.
NEUTRAL = "#8b95a1"
# §5.6 status.warning(라이트) — 확인이 필요한 상태: RiskGate 거절, 강제 청산 판단.
STATUS_WARNING = "#b54708"
# §5.6 status.danger(라이트) — 실행 실패.
STATUS_DANGER = "#d22030"


def _to_int(value: str) -> int:
    """Discord embed는 색을 정수로 받는다. hex 문자열이 SSOT다."""
    return int(value.lstrip("#"), 16)


COLOR_NEUTRAL = _to_int(NEUTRAL)
COLOR_WARNING = _to_int(STATUS_WARNING)
COLOR_DANGER = _to_int(STATUS_DANGER)

__all__ = [
    "COLOR_DANGER",
    "COLOR_NEUTRAL",
    "COLOR_WARNING",
    "NEUTRAL",
    "STATUS_DANGER",
    "STATUS_WARNING",
]
