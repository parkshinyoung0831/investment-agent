"""지주회사 재편으로 CIK가 바뀐 상장사의 이전 제출자.

재편(새 지주회사가 기존 회사를 100% 자회사로 두고 ticker를 넘겨받는 것)은 사업·재무제표가 그대로
이어지는데 SEC 제출자(CIK)만 새로 생긴다. 저장 identity가 CIK라, 이 표가 없으면 ticker는 새 CIK의
한두 분기 재무만 보고 그 전 10년이 사라진다(XOM은 2026년 재편 뒤 재무가 1분기뿐이었다).

- 회계상 같은 회사가 이어지는 재편만 싣는다. 합병으로 다른 회사를 인수한 경우(SW: 회계상 인수자
  Smurfit Kappa는 SEC 제출자가 아니었다)나 분할 신설(GEV·SOLV·SNDK)은 싣지 않는다.
- 같은 회계기간을 두 제출자가 모두 냈으면 읽기 경계가 기간마다 가장 늦게 제출된 버전 하나를 고른다.
"""
from __future__ import annotations

from typing import Iterable

# 현재 CIK → 이전 제출자 CIK들(10자리). SEC submissions로 확인한 재편만 둔다.
PREDECESSOR_CIKS: dict[str, tuple[str, ...]] = {
    "0002115436": ("0000034088",),  # ExxonMobil Holdings ← Exxon Mobil Corp (2026)
    "0002012383": ("0001364742",),  # BlackRock ← BlackRock Finance(옛 BlackRock Inc, 2024)
    "0001996862": ("0001144519",),  # Bunge Global SA ← Bunge Ltd (2023)
    "0002011641": ("0001832433",),  # Ferguson Enterprises ← Ferguson plc (2024)
    "0002041610": ("0000813828",),  # Paramount Skydance ← Paramount Global (2025)
}


def predecessors(cik: str) -> tuple[str, ...]:
    return PREDECESSOR_CIKS.get(str(cik).zfill(10), ())


def with_predecessors(ciks: Iterable[str]) -> dict[str, str]:
    """CIK들과 그 이전 제출자 → 현재 CIK. 읽기 경계가 이전 제출자의 행을 현재 종목으로 돌려 준다."""
    output: dict[str, str] = {}
    for cik in ciks:
        current = str(cik).zfill(10)
        output[current] = current
        for predecessor in predecessors(current):
            output.setdefault(predecessor, current)
    return output


__all__ = ["PREDECESSOR_CIKS", "predecessors", "with_predecessors"]
