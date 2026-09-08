"""Atlanta Fed 공식 스프레드시트에서 GDPNow 과거 스냅샷을 복원한다."""
from __future__ import annotations

import math
from datetime import date, datetime
from io import BytesIO
from typing import Any

import requests

from investment_agent.platform.retry import retry_on_5xx

ARCHIVE_URL = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
    "cqer/researchcq/gdpnow/GDPTrackingModelDataAndForecasts.xlsx"
)
ARCHIVE_SHEETS = ("TrackingDeepArchives", "TrackingArchives")


@retry_on_5xx()
def fetch_workbook() -> bytes:
    """공식 공개 파일을 메모리로 받는다. 파일은 DB나 Storage에 보관하지 않는다."""
    response = requests.get(ARCHIVE_URL, timeout=120)
    response.raise_for_status()
    content = response.content
    if not content.startswith(b"PK"):
        raise ValueError("GDPNow archive response is not an xlsx workbook")
    return content


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        parsed = str(value).strip().split(" ", 1)[0]
        return date.fromisoformat(parsed)
    except (TypeError, ValueError):
        return None


def _quarter_start(value: Any) -> date | None:
    parsed = _as_date(value)
    if parsed is None:
        return None
    month = ((parsed.month - 1) // 3) * 3 + 1
    return date(parsed.year, month, 1)


def _frame_rows(frame: Any, *, ref_period_start: date) -> list[dict[str, Any]]:
    """두 공식 archive 시트의 공통 열 세 개만 표준 예상 행으로 바꾼다."""
    required = {"Forecast Date", "Quarter being forecasted", "GDP Nowcast"}
    if not required.issubset(set(frame.columns)):
        missing = ", ".join(sorted(required - set(frame.columns)))
        raise ValueError(f"GDPNow archive columns missing: {missing}")

    rows: list[dict[str, Any]] = []
    for item in frame.to_dict("records"):
        snapshot = _as_date(item.get("Forecast Date"))
        ref_period = _quarter_start(item.get("Quarter being forecasted"))
        try:
            value = float(item.get("GDP Nowcast"))
        except (TypeError, ValueError):
            continue
        if (
            snapshot is None or ref_period is None or ref_period < ref_period_start
            or not math.isfinite(value)
        ):
            continue
        rows.append({
            "series_id": "US_GDP",
            "ref_period": ref_period.isoformat(),
            "snapshot_date": snapshot.isoformat(),
            "source": "atlanta_fed_gdpnow_archive",
            "forecast_kind": "nowcast",
            "value": value,
        })
    return rows


def parse_workbook(content: bytes, *, ref_period_start: date) -> list[dict[str, Any]]:
    """2011년 이후 완료 분기의 모든 GDPNow 업데이트를 중복 없이 읽는다."""
    import pandas as pd  # 백필에서만 쓰는 무거운 의존성이라 지연 import한다.

    frames = {
        sheet: pd.read_excel(BytesIO(content), sheet_name=sheet, engine="openpyxl")
        for sheet in ARCHIVE_SHEETS
    }
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for sheet in ARCHIVE_SHEETS:
        for row in _frame_rows(frames[sheet], ref_period_start=ref_period_start):
            deduped[(row["ref_period"], row["snapshot_date"])] = row
    return [deduped[key] for key in sorted(deduped)]


def fetch_rows(*, ref_period_start: date) -> list[dict[str, Any]]:
    """공식 파일 다운로드와 파싱을 한 번에 수행한다."""
    return parse_workbook(fetch_workbook(), ref_period_start=ref_period_start)
