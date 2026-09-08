"""Formatting helpers for gurus notification cards."""
from __future__ import annotations

from typing import Any


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def pct(value: Any, digits: int = 1) -> str:
    return f"{number(value) * 100:.{digits}f}%"


def signed_pct(value: Any, digits: int = 1) -> str:
    n = number(value) * 100
    return f"{n:+.{digits}f}%"


def money(value: Any) -> str:
    n = number(value)
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1_000_000_000:
        return f"{sign}${n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{sign}${n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{sign}${n / 1_000:.1f}K"
    return f"{sign}${n:,.0f}"


def quarter(period_end: str) -> str:
    year, month, _ = period_end.split("-")
    q = (int(month) - 1) // 3 + 1
    return f"{year} Q{q}"


def initials(name: str) -> str:
    parts = [p for p in name.replace(".", " ").split() if p]
    return "".join(p[0].upper() for p in parts[:2]) or "?"


def share_delta(row: dict) -> float | None:
    curr = row.get("shares")
    prev = row.get("prev_shares")
    if curr is None or prev in (None, 0):
        return None
    return (number(curr) - number(prev)) / abs(number(prev))


def percentage_point(curr: Any, prev: Any, digits: int = 1) -> str:
    """두 비중의 차이를 퍼센트포인트 문자열로 표시."""
    return f"{(number(curr) - number(prev)) * 100:+.{digits}f}%p"
