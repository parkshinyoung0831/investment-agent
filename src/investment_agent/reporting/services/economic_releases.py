"""경제지표 마스터·발표 자연키의 읽기 계약.

화면은 두 가지를 domain에 직접 물어보고 있었다 — 지표 마스터에 수집 계약을 결합하는
규칙과, 발표 자연키의 형식이다. 둘 다 `econ_calendar` domain이 정당한 owner라 옮기지
않고, **화면이 알아야 할 만큼만** 여기서 좁혀 낸다.

특히 키 파싱은 형식이 틀렸을 때 domain이 `ValueError`를 던진다. 화면에 필요한 답은
"유효한가"이지 예외 종류가 아니므로 여기서는 None으로 돌려준다 — 화면이 domain의
실패 표현 방식에 묶이지 않게 한다.
"""
from __future__ import annotations

from typing import Any

from investment_agent.data.macro.domain.releases.release_catalog import enrich_series
from investment_agent.data.macro.domain.releases.identity import split_event_key


def enriched_series(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """지표 마스터 행에 코드가 가진 수집 계약을 결합한다.

    계약이 어긋난 지표는 domain이 예외로 막는다 — 잘못된 단위·시간대를 화면이
    그럴듯하게 그리는 것보다 조회가 실패하는 편이 낫다. 그 판단은 여기서 뒤집지 않는다.
    """
    return [enrich_series(row) for row in rows]


def parse_event_key(value: object) -> tuple[str, str] | None:
    """`SERIES_ID:YYYY-MM-DD` 자연키를 (series_id, ref_period)로. 형식이 아니면 None."""
    try:
        return split_event_key(str(value or "").strip())
    except ValueError:
        return None


__all__ = ["enriched_series", "parse_event_key"]
