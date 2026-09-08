"""세그먼트 wide 저장 컬럼과 축·기간 호환 규칙."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SegmentMetric:
    """한 표준 지표가 저장될 수 있는 기간과 세그먼트 축을 정의한다."""

    period: str
    segment_types: frozenset[str]
    company_column: str | None = None


_ALL_CORE_AXES = frozenset({"business", "product", "geographic"})

SEGMENT_METRICS: dict[str, SegmentMetric] = {
    "revenue": SegmentMetric("flow", _ALL_CORE_AXES, "revenue"),
    "profit_loss": SegmentMetric("flow", frozenset({"business"})),
    "assets": SegmentMetric("instant", frozenset({"business"}), "assets"),
}

SEGMENT_WIDE_COLUMNS: tuple[str, ...] = tuple(SEGMENT_METRICS)
SEGMENT_WIDE_COLUMN_SET: frozenset[str] = frozenset(SEGMENT_WIDE_COLUMNS)
FLOW_COLUMNS: tuple[str, ...] = tuple(
    key for key, spec in SEGMENT_METRICS.items() if spec.period == "flow"
)
INSTANT_COLUMNS: tuple[str, ...] = tuple(
    key for key, spec in SEGMENT_METRICS.items() if spec.period == "instant"
)
EXPENSE_COLUMNS: tuple[str, ...] = ()


def is_compatible(column_key: str, segment_type: str, source_period_kind: str) -> bool:
    """지표 의미에 맞는 축·XBRL 기간 조합만 허용한다."""
    spec = SEGMENT_METRICS.get(column_key)
    if spec is None or segment_type not in spec.segment_types:
        return False
    if spec.period == "instant":
        return source_period_kind == "instant"
    return source_period_kind in {"quarter", "annual", "ytd"}

