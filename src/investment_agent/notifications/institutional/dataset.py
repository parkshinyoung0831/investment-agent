"""거장 알림용 DB 원본을 분석 스냅샷으로 조립한다."""
from __future__ import annotations

from investment_agent.data.institutional.domain.analysis import build_snapshot
from investment_agent.reporting.notifications.institutional import db


def load_snapshot() -> dict[str, list[dict]]:
    """v1 원천 표를 결정적 카드 분석 스냅샷으로 정규화한다."""
    return build_snapshot(db.load_analysis_source())
