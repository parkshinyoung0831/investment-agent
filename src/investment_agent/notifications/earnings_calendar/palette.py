"""발표 예정 카드 색 기준(SSOT).

토큰 값은 DESIGN-system.md에서 가져온다. 이 카드는 예정을 알릴 뿐 등락을 말하지
않으므로 **상승·하락 색을 쓰지 않는다** — 강조는 Brand Blue 하나뿐이고, 예정일의
불확실성 등급은 색이 아니라 배지 글자로 말한다(확정이 아닌 걸 초록/빨강으로 칠하면
없는 확신을 주장하게 된다).
"""
from __future__ import annotations

PRIMARY = "#3182f6"
INK = "#0a0b0d"
BODY = "#5b616e"
MUTED = "#7c828a"
MUTED_SOFT = "#a8acb3"
HAIRLINE = "#dee1e6"
CANVAS = "#ffffff"
SURFACE_STRONG = "#eef0f3"
SURFACE_DARK = "#0a0b0d"
SURFACE_DARK_ELEVATED = "#16181c"
ON_DARK = "#ffffff"
ON_DARK_SOFT = "#a8acb3"
AMBER = "#f4b000"

# 불확실성 등급 → 배지 문구. 어떤 등급도 '확정'이라고 말하지 않는다.
CONFIDENCE_LABELS = {
    "estimated": "예정",
    "shifted": "변경됨",
    "stale": "기준 오래됨",
}


def tokens() -> dict[str, str]:
    """템플릿에 넘길 CSS 변수 묶음 — 템플릿에 hex를 인라인하지 않기 위한 통로."""
    return {
        "primary": PRIMARY,
        "ink": INK,
        "body": BODY,
        "muted": MUTED,
        "muted_soft": MUTED_SOFT,
        "hairline": HAIRLINE,
        "canvas": CANVAS,
        "surface_strong": SURFACE_STRONG,
        "surface_dark": SURFACE_DARK,
        "surface_dark_elevated": SURFACE_DARK_ELEVATED,
        "on_dark": ON_DARK,
        "on_dark_soft": ON_DARK_SOFT,
        "accent_yellow": AMBER,
    }
