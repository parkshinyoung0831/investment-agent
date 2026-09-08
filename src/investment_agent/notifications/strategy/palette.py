"""전략 카드 색 기준(SSOT) — DESIGN-system.md 토큰과 배분 막대 규칙.

원칙:
1. 색 voltage는 Brand Blue 하나. 배분 막대는 같은 파랑의 **농도 단계**로 비중 순서를
   표현하고, 두 번째 브랜드 색을 만들지 않는다.
2. 방어자산(단기채·채권류)만 중립 회색으로 빼서 "파란 면적 = 위험자산 비중"이 바로
   읽히게 한다. 회색은 브랜드 색이 아니라 표면 색이라 규칙을 깨지 않는다.
3. 상승·하락 색은 텍스트 전용. 신규 편입/제거 표시에만 쓰고 배경을 칠하지 않는다.
"""
from __future__ import annotations

PRIMARY = "#3182f6"
PRIMARY_ACTIVE = "#003ecc"
INK = "#0a0b0d"
BODY = "#5b616e"
MUTED = "#7c828a"
MUTED_SOFT = "#a8acb3"
HAIRLINE = "#dee1e6"
HAIRLINE_SOFT = "#eef0f3"
CANVAS = "#ffffff"
SURFACE_SOFT = "#f7f7f7"
SURFACE_STRONG = "#eef0f3"
SURFACE_DARK = "#0a0b0d"
SURFACE_DARK_ELEVATED = "#16181c"
ON_PRIMARY = "#ffffff"
ON_DARK = "#ffffff"
ON_DARK_SOFT = "#a8acb3"
SEMANTIC_UP = "#05b169"
SEMANTIC_DOWN = "#cf202f"
ACCENT_YELLOW = "#f4b000"

# 현금성·채권 자산. 배분 막대에서 파랑 대신 중립으로 칠해 위험 노출을 눈에 띄게 한다.
DEFENSIVE_TICKERS = frozenset({"BIL", "AGG", "IEF", "TLT", "TIP"})

# 비중 순위별 파랑 농도. 1위가 가장 진하고 뒤로 갈수록 옅어진다.
# 하한을 0.34까지만 내린다 — 더 내리면 어두운 표면 위에서 조각이 배경에 묻힌다.
_BLUE_STEPS = (1.00, 0.80, 0.64, 0.50, 0.40, 0.34)
_GREY_STEPS = (0.62, 0.52, 0.44, 0.38, 0.33, 0.29)


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


def segment_color(ticker: str, rank: int) -> str:
    """배분 막대 한 칸의 색. rank는 비중 내림차순 0-based."""
    steps = _GREY_STEPS if ticker in DEFENSIVE_TICKERS else _BLUE_STEPS
    base = MUTED_SOFT if ticker in DEFENSIVE_TICKERS else PRIMARY
    return _rgba(base, steps[min(rank, len(steps) - 1)])


def risk_weight(alloc: dict[str, float]) -> float:
    """위험자산 비중 합계(0~1). 헤더의 위험 노출 표시에 쓴다."""
    return sum(w for t, w in alloc.items() if t not in DEFENSIVE_TICKERS)


def turnover_tone(turnover_pct: float, *, is_first: bool) -> str:
    """턴오버 크기 → 배지 톤 키. 색은 텍스트·점에만 적용한다."""
    if is_first:
        return "new"
    if turnover_pct >= 50:
        return "high"
    if turnover_pct >= 20:
        return "mid"
    if turnover_pct > 0:
        return "low"
    return "flat"


TURNOVER_COLORS = {
    "new": PRIMARY,
    "high": SEMANTIC_DOWN,
    "mid": ACCENT_YELLOW,
    "low": MUTED_SOFT,
    "flat": MUTED,
}

TOKENS = {
    "primary": PRIMARY,
    "primary_active": PRIMARY_ACTIVE,
    "ink": INK,
    "body": BODY,
    "muted": MUTED,
    "muted_soft": MUTED_SOFT,
    "hairline": HAIRLINE,
    "hairline_soft": HAIRLINE_SOFT,
    "canvas": CANVAS,
    "surface_soft": SURFACE_SOFT,
    "surface_strong": SURFACE_STRONG,
    "surface_dark": SURFACE_DARK,
    "surface_dark_elevated": SURFACE_DARK_ELEVATED,
    "on_primary": ON_PRIMARY,
    "on_dark": ON_DARK,
    "on_dark_soft": ON_DARK_SOFT,
    "semantic_up": SEMANTIC_UP,
    "semantic_down": SEMANTIC_DOWN,
    "accent_yellow": ACCENT_YELLOW,
    "turnover_new": TURNOVER_COLORS["new"],
    "turnover_high": TURNOVER_COLORS["high"],
    "turnover_mid": TURNOVER_COLORS["mid"],
    "turnover_low": TURNOVER_COLORS["low"],
    "turnover_flat": TURNOVER_COLORS["flat"],
}
