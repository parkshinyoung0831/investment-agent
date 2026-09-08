"""13F 적재 뒤의 운영 인계.

수집은 data owner가 소유한다. 이 모듈은 이미 적재된 공시를 알림 흐름에서
빼 두는 인계 한 단계만 소유한다.
"""
from __future__ import annotations

from investment_agent.operations.db import seed_institutional_baseline
from investment_agent.reporting.notifications.institutional import db as notification_db


def seed_notification_baseline() -> int:
    """현재 13F 스냅샷을 이미 아는 것으로 표시한다."""
    return seed_institutional_baseline(notification_db.load_analysis_source()["filings"])
