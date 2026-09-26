"""총차입 정의. reporting과 research가 예전에 각자 구현해 값이 갈렸다(감사 RR2-09).

reporting은 운용리스 부채를 포함했고(`fundamentals.v_quality`/`v_value` 뷰와 정렬) research는
빠뜨렸다 — 유통·항공·통신처럼 운용리스가 큰 업종에서 카드의 순부채·부채비율과 research의
`quality_debt_to_equity`가 체계적으로 달랐다. 이 함수가 유일한 정의다.
"""
from __future__ import annotations

import math
from typing import Any, Mapping


def _f(value: Any) -> float | None:
    """유한한 float만. NaN·Infinity·bool·None은 모른다(None) — research feature도 이 함수를 쓴다."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def total_debt(row: Mapping[str, Any]) -> float | None:
    """단기차입·유동성 장기부채·장기부채·운용리스 부채(유동/비유동) 합계.

    세 차입 컬럼은 서로 겹치지 않게 정의돼 있어 더할 수 있다. 회사가 보고한 총계
    (`total_debt_including_current`)는 쓰지 않는다 — 리스를 빼고 세는 값이라, 그것이 있는
    회사와 없는 회사의 부채비율이 다른 정의로 계산된다. 구성요소가 하나도 없으면
    모른다(None) — 0으로 접으면 부채 없는 회사처럼 보여 순부채·부채비율이 좋게 나온다.
    """
    parts = (
        _f(row.get("short_term_debt")),
        _f(row.get("current_portion_of_long_term_debt")),
        _f(row.get("long_term_debt")),
        _f(row.get("operating_lease_current_debt_equivalent")),
        _f(row.get("operating_lease_non_current_debt_equivalent")),
    )
    known = [value for value in parts if value is not None]
    return sum(known) if known else None


__all__ = ["total_debt"]
