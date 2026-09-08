"""Reporting 결과를 Discord embed로 표현한다. 투자 계산과 데이터 조회는 하지 않는다."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from investment_agent.platform.serialization import canonical_json
from investment_agent.reporting.models import DataResult


def render_report(report: DataResult, *, title: str, fields: Mapping[str, str]) -> dict[str, Any]:
    """한 행당 하나의 embed. 컬럼 이름→표시 라벨을 호출자가 명시한다.

    오류/빈 결과를 성공 카드로 만들지 않는다. 공개 숫자는 계산하거나 추측하지 않으며
    NULL은 '—'로 표시한다. 메시지 크기 초과는 전송 경계에서 오류로 드러낸다.
    """
    if report.status != "ok" or not report.rows:
        raise ValueError("only a nonempty successful report can be rendered")
    if not report.source.startswith("reporting."):
        raise ValueError("renderer requires a reporting read model")
    if not fields or not title.strip():
        raise ValueError("report title and explicit fields are required")
    embeds = []
    for row in report.rows:
        values = []
        for column, label in fields.items():
            if column not in row:
                raise ValueError("report field is missing")
            value = row[column]
            text = "—" if value is None else canonical_json(value) if isinstance(value, (dict, list)) else str(value)
            values.append({"name": label, "value": text or "—", "inline": False})
        embeds.append({"title": title, "fields": values, "footer": {"text": report.source}})
    return {"embeds": embeds}
