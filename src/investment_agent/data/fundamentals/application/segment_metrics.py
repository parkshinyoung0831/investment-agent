"""차원이 있는 공시 fact에서 세그먼트 지표를 만든다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SegmentMetricBatch:
    """직접 공시 지표와 분기 파생에 필요한 YTD 관측값."""

    metric_rows: list[dict]
    ytd_rows: list[dict]
    unmapped_concepts: frozenset[str]


def build_segment_metrics(
    cik: str,
    filing: dict,
    facts: list[dict],
    period_kind: str,
    concept_registry: dict[str, Any] | None = None,
) -> SegmentMetricBatch:
    """한 CIK/accession_no의 세그먼트 지표 후보를 생성한다."""
    from investment_agent.data.fundamentals.domain.services.build_segment_metrics import (
        to_segment_wide_rows,
        ytd_flow_rows,
    )

    metric_rows, unmapped = to_segment_wide_rows(
        cik,
        filing,
        facts,
        period_kind,
        concept_registry,
    )
    return SegmentMetricBatch(
        metric_rows=metric_rows,
        ytd_rows=ytd_flow_rows(
            cik,
            filing,
            facts,
            period_kind,
            concept_registry,
        ),
        unmapped_concepts=frozenset(unmapped),
    )

