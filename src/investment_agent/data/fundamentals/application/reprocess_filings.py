"""정책 변경 뒤 최신 세그먼트 공시를 안전하게 재처리한다."""
from __future__ import annotations

from investment_agent.data.fundamentals.application import (
    SegmentFilingSource,
    SegmentMetricRepository,
)
from investment_agent.data.fundamentals.application.sync_recent_filings import (
    sync_segment_filings,
)


def reprocess_filings(
    period_kind: str,
    *,
    source: SegmentFilingSource,
    repository: SegmentMetricRepository,
    lookback_days: int = 7,
    watchlist_only: bool = False,
) -> dict:
    """daily_xbrl로 적재된 최신 공시를 다시 파싱해 원자 교체한다."""
    return sync_segment_filings(
        period_kind,
        source=source,
        repository=repository,
        lookback_days=lookback_days,
        reprocess=True,
        watchlist_only=watchlist_only,
    )

