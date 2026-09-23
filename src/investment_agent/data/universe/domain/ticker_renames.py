"""과거 S&P 500 멤버십에 옛 표기로 남은 종목의 현재 표기.

과거 멤버십 스냅샷은 그때의 ticker 문자열을 그대로 갖는다. 개명된 회사의 옛 ticker는 종목 마스터에 CIK 없는
자리표시 행으로만 남아 가격과 이어지지 않아, 과거 재현에서 그 회사가 통째로 빠졌다(생존 편향). 같은 회사가
표기만 바꾼 경우만 적는다 — 인수·합병으로 다른 회사가 된 경우는 넣지 않는다(DISCA·DISCK는 WarnerMedia를
인수한 Discovery가 WBD로 이름을 바꾼 존속 회사라 넣는다).
"""
from __future__ import annotations

from typing import Iterable

# 옛 ticker → 현재 ticker. 공급자(Yahoo)는 현재 ticker 아래에 개명 전 이력까지 이어서 준다.
HISTORICAL_TICKER_RENAMES: dict[str, str] = {
    "DISCA": "WBD",
    "DISCK": "WBD",
    "FBHS": "FBIN",
    "FLT": "CPAY",
    "GPS": "GAP",
    "WLTW": "WTW",
}


def current_symbols(symbols: Iterable[str]) -> list[str]:
    """과거 표기를 현재 표기로 바꾼 정렬된 목록. 같은 회사의 두 옛 표기는 하나가 된다."""
    return sorted({HISTORICAL_TICKER_RENAMES.get(str(symbol).upper(), str(symbol).upper()) for symbol in symbols})


__all__ = ["HISTORICAL_TICKER_RENAMES", "current_symbols"]
