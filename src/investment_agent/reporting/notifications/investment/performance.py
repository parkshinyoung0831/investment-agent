"""성과 owner의 지속 보고서를 읽는 알림 계약."""
from __future__ import annotations

from investment_agent.trading.performance.repository import PerformanceRepository


def latest_performance():
    return PerformanceRepository().latest_performance()


def performance_reports():
    """동일 occurrence는 마지막 revision만 전달하고 미발송 과거 청산도 보존한다."""
    latest = {}
    for row in PerformanceRepository().reports():
        latest[(row["broker_account_hash"], row["execution_mode"], row["report_kind"], row["occurrence"])] = row
    reports = list(latest.values())
    from datetime import datetime, timezone
    from investment_agent.trading.supabase_repository import SupabaseRepository
    from investment_agent.trading.performance.service import summarize_recommendations
    from investment_agent.platform.serialization import stable_id
    now = datetime.now(timezone.utc)
    experiences = SupabaseRepository().decision_experience_rows(as_of_at=now)
    comparison = summarize_recommendations(experiences, now)
    if comparison['horizons']:
        moment = max(row['available_at'] for row in experiences)
        row = dict(report_kind='recommendation', execution_mode='shadow', broker_account_hash='system-decisions',
                   as_of_at=moment, occurrence=moment[:10], currency='USD', recommendation=comparison, quality_issues=[])
        row['report_id'] = stable_id('decision_performance', row)
        reports.append(row)
    return reports
