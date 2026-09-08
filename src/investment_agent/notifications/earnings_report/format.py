"""실적 카드 숫자 포매팅 — 금액·퍼센트·전년비."""
from __future__ import annotations


def money(v: float | None) -> str:
    """달러 금액을 사람이 읽기 좋은 단위로. 예) 1.23B, 456.7M, -12.3M."""
    if v is None:
        return "—"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:.1f}K"
    return f"{sign}${a:.0f}"


def num(v: float | None, digits: int = 2) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def pct(v: float | None, *, digits: int = 1) -> str:
    """비율(0.123)을 12.3%로. None이면 대시."""
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def yoy(v: float | None) -> str:
    """전년비 비율을 부호 포함 퍼센트로. 방향은 템플릿 색으로 표현한다."""
    if v is None:
        return "—"
    p = v * 100
    return f"{'+' if p >= 0 else ''}{p:.1f}% YoY"
