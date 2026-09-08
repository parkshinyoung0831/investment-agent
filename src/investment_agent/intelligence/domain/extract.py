"""게시물 본문에서 종목을 찾아낸다.

## 왜 fail-closed인가

S&P 500에는 `A`, `ALL`, `IT`, `ON`, `NOW`, `HAS`처럼 평범한 영어 단어와 똑같은
티커가 있다. `\\b[A-Z]{1,5}\\b`로 긁으면 "IT IS ON ALL" 한 문장이 종목 4개
언급이 된다. 그렇게 모인 표는 집계에 쓸 수 없다.

그래서 세 단계로 좁힌다.

1. `$` 캐시태그는 무조건 인정한다 — 사람이 종목이라고 밝힌 것이다.
2. 맨 심볼은 universe가 추적하는 종목이면서 모호 목록에 없을 때만 인정한다.
3. 모호한 티커는 캐시태그로만 잡힌다.

어느 단계로 잡았는지는 `match_kind`와 `confidence`에 남는다. 나중에
"캐시태그만 쓰겠다"는 판단을 할 수 있어야 하기 때문이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

# 짧은 심볼은 평문에서 구분되지 않는다. 길이로 거르는 편이 목록을 손으로 채우는
# 것보다 오래간다 — 1~2글자 티커는 예외 없이 모호하다.
MIN_PLAIN_SYMBOL_LENGTH = 3

# 3글자 이상이면서 평범한 영어 단어이기도 한 티커. 목록을 늘리는 것은 안전한
# 방향이다(놓치는 쪽이 거짓 언급을 만드는 쪽보다 낫다).
AMBIGUOUS_TICKERS = frozenset(
    {
        "ALL", "ARE", "BIG", "CAR", "CAT", "DAY", "EVER", "FAST", "FUN", "GAIN",
        "GOOD", "HAS", "HOPE", "HOT", "JOB", "KEY", "LIFE", "LIVE", "LOVE", "LOW",
        "MAIN", "MAN", "NEW", "NICE", "NOW", "ONE", "OPEN", "OUT", "PLAN", "PLAY",
        "POST", "REAL", "RUN", "SAFE", "SAVE", "SEE", "STAY", "STEP", "TAP",
        "TEAM", "TECH", "TELL", "TRUE", "TWO", "USA", "WELL", "WORK", "YOU",
    }
)

CONFIDENCE = {"cashtag": 1.0, "queried": 1.0, "symbol": 0.6, "company_name": 0.4}

_CASHTAG_RE = re.compile(r"\$([A-Z][A-Z.\-]{0,9})\b")
_SYMBOL_RE = re.compile(r"(?<![$\w])([A-Z][A-Z.\-]{0,9})(?![\w])")


@dataclass(frozen=True)
class TickerMatch:
    """어떤 종목을, 어떤 방식으로 찾았는지."""

    ticker: str
    match_kind: str
    confidence: float


def is_ambiguous(ticker: str) -> bool:
    """캐시태그 없이는 인정하지 않을 심볼인가."""
    symbol = str(ticker).upper()
    return len(symbol) < MIN_PLAIN_SYMBOL_LENGTH or symbol in AMBIGUOUS_TICKERS


def find_tickers(text: object, *, tracked: frozenset[str] | set[str]) -> list[TickerMatch]:
    """본문에서 종목 언급을 찾는다. universe가 모르는 심볼은 언급이 아니다."""
    body = str(text or "")
    if not body:
        return []
    universe = {str(item).upper() for item in tracked}
    found: dict[tuple[str, str], TickerMatch] = {}

    for symbol in _CASHTAG_RE.findall(body):
        ticker = symbol.upper()
        if ticker in universe:
            found[(ticker, "cashtag")] = TickerMatch(ticker, "cashtag", CONFIDENCE["cashtag"])

    for symbol in _SYMBOL_RE.findall(body):
        ticker = symbol.upper()
        if ticker not in universe or is_ambiguous(ticker):
            continue
        found[(ticker, "symbol")] = TickerMatch(ticker, "symbol", CONFIDENCE["symbol"])

    return [found[key] for key in sorted(found)]


__all__ = [
    "AMBIGUOUS_TICKERS",
    "CONFIDENCE",
    "MIN_PLAIN_SYMBOL_LENGTH",
    "TickerMatch",
    "find_tickers",
    "is_ambiguous",
]
