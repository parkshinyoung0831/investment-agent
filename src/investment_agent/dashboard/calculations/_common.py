"""대시보드 계산 기본 파싱·변환 유틸리티."""
from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

_DISPLAY_TZ = ZoneInfo("Asia/Seoul")

def today_kst() -> date:
    """화면이 말하는 '오늘'. 보는 사람이 한국에 있으므로 KST 기준이다.

    실행 환경의 로컬 날짜(`date.today()`)를 쓰면 UTC로 도는 러너에서 00~09시 KST 동안
    하루가 밀린다. 그 구간이 주 경계에 걸리면 조회 창이 통째로 바뀌므로, 오늘을 쓰는
    쪽은 화면이든 테스트든 전부 이 함수를 지난다.
    """
    return datetime.now(_DISPLAY_TZ).date()


from investment_agent.platform.serialization import finite_float


def finite_number(value: Any) -> float | None:
    """유한한 숫자만 ``float``로 반환하고 결측·불리언·무한대는 ``None``으로 둔다."""
    if isinstance(value, np.bool_):
        return None
    return finite_float(value)


def covariance_to_correlation(matrix: Any) -> list[list[float]] | None:
    """저장된 정방 공분산 행렬을 화면용 상관계수 행렬로 안전하게 바꾼다."""

    if not isinstance(matrix, (list, tuple)) or not matrix:
        return None
    size = len(matrix)
    rows: list[list[float]] = []
    for raw_row in matrix:
        if not isinstance(raw_row, (list, tuple)) or len(raw_row) != size:
            return None
        parsed = [finite_number(value) for value in raw_row]
        if any(value is None for value in parsed):
            return None
        rows.append([float(value) for value in parsed if value is not None])
    variances = [rows[index][index] for index in range(size)]
    if any(value <= 0.0 for value in variances):
        return None
    return [
        [
            max(
                -1.0,
                min(
                    1.0,
                    rows[row_index][column_index]
                    / math.sqrt(variances[row_index] * variances[column_index]),
                ),
            )
            for column_index in range(size)
        ]
        for row_index in range(size)
    ]


def parse_datetime_safe(value: Any) -> datetime | None:
    """날짜·ISO 문자열을 UTC datetime으로 안전하게 해석하고 실패하면 ``None``을 반환한다."""
    if value is None or isinstance(value, (bool, int, float, np.number)):
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        return None
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime(value.year, value.month, value.day)
        else:
            text = str(value).strip()
            if not text:
                return None
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def parse_date_safe(value: Any) -> date | None:
    """날짜 입력을 안전하게 ``date``로 바꾸고 해석할 수 없으면 ``None``을 반환한다."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = parse_datetime_safe(value)
    return parsed.date() if parsed is not None else None


def _records(value: Any) -> list[dict[str, Any]]:
    """DataFrame 또는 매핑 시퀀스를 복사된 레코드 목록으로 정규화한다."""
    if isinstance(value, pd.DataFrame):
        return [dict(row) for row in value.to_dict("records")]
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return []
    try:
        return [dict(row) for row in value if isinstance(row, Mapping)]
    except TypeError:
        return []
