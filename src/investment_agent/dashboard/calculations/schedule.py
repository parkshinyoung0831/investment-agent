"""대시보드 일정 지평·D-Day 계산."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from investment_agent.reporting.services.earnings.schedule import week_window

# ── 발표 예정 조회 창 ────────────────────────────────────────────────
# Discord `#실적-캘린더` 카드는 '이번 주(월–일)'만 주장한다. 화면은 방금 지나간 발표와
# 다음 분기 일정까지 함께 봐야 판단이 되므로 창을 넓히되, Discord 규칙을 선택지로 남긴다.
# (라벨 -> 시작 오프셋일, 끝 오프셋일, 기간별 분리). None이면 주간 창을 쓴다.
SCHEDULE_HORIZONS: dict[str, tuple[int | None, int | None, bool]] = {
    "지난 7일 + 향후 21일": (-7, 21, True),
    "이번 주 (Discord 규칙)": (None, None, False),
    "향후 90일": (0, 90, True),
}
DEFAULT_SCHEDULE_HORIZON = "지난 7일 + 향후 21일"


def schedule_window(horizon: str, today: date) -> tuple[date, date, bool]:
    """선택한 지평을 실제 날짜 구간으로 바꾼다.

    반환값은 ``(시작일, 종료일, 기간별 분리 여부)``다. 모르는 라벨은 예외 대신 기본 창으로
    되돌린다 — 화면이 창 하나 때문에 멈추면 안 된다.
    """
    start_offset, end_offset, group_by_target = SCHEDULE_HORIZONS.get(
        horizon, SCHEDULE_HORIZONS[DEFAULT_SCHEDULE_HORIZON]
    )
    if start_offset is None or end_offset is None:
        start, end = week_window(today)
        return start, end, group_by_target
    return (
        today + timedelta(days=start_offset),
        today + timedelta(days=end_offset),
        group_by_target,
    )


def d_day_label(value: Any) -> str:
    """Discord 예정 카드와 같은 방향으로 남은 날짜를 표시한다."""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return "—"
    if days == 0:
        return "오늘"
    return f"D-{days}" if days > 0 else f"D+{abs(days)}"


# ── 매크로 지표 환원 (Discord 코어/감시 카드와 같은 규칙) ─────────────────
# ETL은 raw 관측값만 저장한다. z·이동평균·52주 고저·경보 등급은 알림이 그때그때
# 계산하므로, 화면도 같은 순수 함수를 호출해야 카드와 숫자가 갈라지지 않는다.

MACRO_SPARK_POINTS = 40
