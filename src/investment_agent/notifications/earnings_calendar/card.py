"""metrics 결과를 템플릿 ctx와 Discord 캡션으로 바꾸는 표시 계층(순수 함수)."""
from __future__ import annotations

from datetime import date

from investment_agent.notifications.earnings_calendar import palette
from investment_agent.reporting.services.earnings import schedule as metrics

_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def _day_label(day: date | None) -> str | None:
    return f"{day.month}/{day.day}({_WEEKDAYS[day.weekday()]})" if day else None


def _target_label(period_end: date | None) -> str | None:
    """추정 기간말 → '3분기' 같은 사람 말. 회계연도가 어긋나는 회사도 있어 달로 적는다."""
    return f"{period_end.year}년 {period_end.month}월 종료 분기" if period_end else None


def _eps_label(value: object) -> str | None:
    try:
        return f"${float(value):.2f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def build(rows: list[dict], today: date, snapshot_date: date | None) -> tuple[dict, str]:
    """(템플릿 ctx, Discord 캡션)."""
    start, end = metrics.week_window(today)
    display = [
        {
            **row,
            "confidence_label": palette.CONFIDENCE_LABELS.get(row["confidence"], "예정"),
            "previous_label": _day_label(row.get("previous_expected")),
            "prior_filed_label": _day_label(row.get("prior_filed_at")),
            "target_label": _target_label(row.get("target_period_end")),
            "eps_label": _eps_label(row.get("eps_avg")),
        }
        for row in rows
    ]
    ctx = {
        "rows": display,
        "window_label": f"{start.month}/{start.day} ~ {end.month}/{end.day}",
        "snapshot_label": _day_label(snapshot_date) or "기준일 미상",
        "tokens": palette.tokens(),
    }
    names = " · ".join(f"{row['ticker']} {row['expected_label']}" for row in display)
    caption = f"**이번 주 실적 발표 예정** ({ctx['window_label']})\n{names}"
    return ctx, caption
