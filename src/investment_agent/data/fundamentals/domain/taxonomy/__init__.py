"""재무지표·XBRL concept·세그먼트 축의 표준 분류 사전."""
from __future__ import annotations

from investment_agent.data.fundamentals.domain.taxonomy.financial_columns import (
    ALL_WIDE_COLUMNS,
    BALANCE_COLUMNS,
    CORE_COLUMNS,
)
from investment_agent.data.fundamentals.domain.taxonomy.segment_metrics import (
    SEGMENT_METRICS,
    SEGMENT_WIDE_COLUMNS,
)

__all__ = [
    "ALL_WIDE_COLUMNS",
    "BALANCE_COLUMNS",
    "CORE_COLUMNS",
    "SEGMENT_METRICS",
    "SEGMENT_WIDE_COLUMNS",
]
