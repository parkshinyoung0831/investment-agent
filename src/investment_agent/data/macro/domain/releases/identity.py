"""경제발표의 자연키를 화면·알림·적재에서 동일하게 읽고 만든다."""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping

_SERIES = re.compile(r"^[A-Z][A-Z0-9_]*$")


def event_key(series_id: str, ref_period: date | str) -> str:
    if not _SERIES.fullmatch(series_id):
        raise ValueError("invalid ECON series_id")
    period = date.fromisoformat(str(ref_period))
    return f"{series_id}:{period.isoformat()}"


def split_event_key(key: str) -> tuple[str, str]:
    parts = str(key).split(":")
    if len(parts) != 2 or event_key(parts[0], parts[1]) != key:
        raise ValueError("ECON event key must be SERIES_ID:YYYY-MM-DD")
    return parts[0], parts[1]


def row_event_key(row: Mapping[str, Any]) -> str:
    return event_key(str(row["series_id"]), str(row["ref_period"]))
