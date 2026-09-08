"""전략 embed의 라벨·숫자 표기 헬퍼. 카탈로그 라벨을 표시용 문자열로 바꾼다."""
from __future__ import annotations

import re

from .constants import MODE_KO, NAMES, STRATEGY_DESC, TICKERS


def ticker_text(ticker: str) -> str:
    return f"{ticker}({TICKERS.get(ticker, '?')})"


def ticker_label(ticker: str) -> str:
    return TICKERS.get(ticker, "?")


def strategy_name(strategy_id: str) -> str:
    return NAMES.get(strategy_id, strategy_id)


def strategy_description(strategy_id: str) -> str:
    return STRATEGY_DESC.get(strategy_id, "")


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def mom(x: float) -> str:
    """Momentum score display: signed percentage-points without a percent sign."""
    return f"{x * 100:+.1f}"


def ym(d: str) -> str:
    """'2026-06-01' -> '2026년 6월'."""
    y, m, _ = d.split("-")
    return f"{y}년 {int(m)}월"


def numf(x: float) -> str:
    """0.0 -> '0', 33.3 -> '33.3'."""
    return f"{x:.0f}" if float(x).is_integer() else f"{x:.1f}"


def mode_label(mode: str) -> str:
    if mode in MODE_KO:
        return MODE_KO[mode]
    m = re.match(r"^Top-4 통과 (\d+)/4$", mode)
    if m:
        n = int(m.group(1))
        return "🏅 상위 4개 모두 편입" if n == 4 else f"🏅 상위 4개 중 {n}개 편입 · 나머지 안전자산"
    m = re.match(r"^편입 (\d+)/5$", mode)
    if m:
        n = int(m.group(1))
        return "📈 5개 모두 추세 양호" if n == 5 else f"📈 5개 중 {n}개 추세 양호 · 나머지 현금"
    return mode
