"""시장 원천의 상대 기간을 표준 회계기간 스냅샷으로 변환한다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class ConsensusBatch:
    """예상치 수집 한 번에서 만들어진 정규화 결과."""

    snapshots: list[dict]
    schedules: list[dict]
    unmapped_rows: list[dict]


def build_earnings_estimates(
    buckets: dict[str, list[dict]],
    fiscal_calendar_rows: list[dict],
    *,
    collected_on: date,
) -> ConsensusBatch:
    """컨센서스와 발표 예정일을 같은 회계기간 키에 맞춘다."""
    from investment_agent.data.fundamentals.domain.services.map_fiscal_periods import (
        normalize_consensus,
    )

    snapshots, schedules, snapshot_issues = normalize_consensus(
        buckets.get("snapshots", []) + buckets.get("trend_seed", []),
        fiscal_calendar_rows,
        collected_on=collected_on,
    )
    return ConsensusBatch(
        snapshots=snapshots,
        schedules=schedules,
        unmapped_rows=list(snapshot_issues),
    )
