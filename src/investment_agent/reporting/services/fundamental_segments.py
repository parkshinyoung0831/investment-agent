"""세그먼트 행의 표시용 파생값 계약.

`display_name`·`period_kind`·`profit_measure_label`은 각각 `member`·`fiscal_period`·
`profit_measure_kind`에서 그대로 나오므로 테이블에 저장하지 않는다. 읽는 시점에 한 번만
만들어 붙이는데, 그 규칙을 화면의 DB 계층이 갖고 있으면 카드와 화면이 같은 세그먼트를
다른 이름으로 부르게 된다. 그래서 Reporting이 소유한다.

사실의 owner는 `fundamentals` domain이다 — 멤버 이름 정규화와 이익 정의 표기는 거기서
읽어 오고, 여기서는 화면·카드가 쓸 모양으로 붙일 뿐이다.
"""
from __future__ import annotations

from typing import Any

from investment_agent.data.fundamentals.domain.services.classify_dimensions import display_member_name
from investment_agent.data.fundamentals.domain.taxonomy.segment_concepts import profit_measure_label


def enrich_segment_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """저장하지 않는 표시용 값을 읽는 시점에 만들어 붙인다."""
    return [
        {
            **row,
            "display_name": display_member_name(row.get("member")),
            "period_kind": "annual" if row.get("fiscal_period") == "FY" else "quarter",
            "profit_measure_label": (
                profit_measure_label(row["profit_measure_kind"])
                if row.get("profit_measure_kind") else None
            ),
            # 2차원 자식 여부. 화면이 1차원만 그릴 때 쓰는 판별식이다.
            "dimension_count": 1 if not row.get("secondary_axis") else 2,
        }
        for row in rows
    ]


__all__ = ["display_member_name", "enrich_segment_rows", "profit_measure_label"]
