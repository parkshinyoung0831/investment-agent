"""Intelligence 저장소의 90일 보존.

## 기준은 발행 시각이다

`collected_at`을 기준으로 잡으면 100일 전 글을 오늘 주워 90일을 더 들고 있게 된다.
기준은 `coalesce(published_at, first_seen_at)`이다 — 오래된 글은 오늘 수집해도
오래된 글이다.

## 왜 news와 social을 함께 지우는가

컷오프가 세 표에 동시에 걸리지 않으면 부모 없는 mention이 남는 창이 반드시 생긴다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from investment_agent.intelligence.domain.models import CollectionRun, PruneResult
from investment_agent.intelligence.repository import IntelligenceRepository
from investment_agent.platform.clock import ensure_aware, utc_now
from investment_agent.platform.logging import get_logger, log_fields

log = get_logger(__name__)

RETENTION_DAYS = 90


def cutoff(now: datetime, *, retention_days: int = RETENTION_DAYS) -> datetime:
    """이 시각보다 앞선 글은 지운다."""
    if retention_days < 1:
        raise ValueError("retention_days must be >= 1")
    return ensure_aware(now) - timedelta(days=retention_days)


def is_within_retention(
    observed_at: datetime,
    *,
    now: datetime,
    retention_days: int = RETENTION_DAYS,
) -> bool:
    """수집 단계에서 미리 거르기 위한 판정.

    저장한 뒤 다음 정리에서 지우면 그 사이 화면과 집계에 잠깐 나타났다 사라진다.
    """
    return ensure_aware(observed_at) >= cutoff(now, retention_days=retention_days)


def prune(
    repository: IntelligenceRepository,
    *,
    now: datetime | None = None,
    retention_days: int = RETENTION_DAYS,
) -> PruneResult:
    """보존 기간을 넘긴 글과 그 언급을 지우고 실행 기록을 남긴다."""
    moment = ensure_aware(now or utc_now())
    boundary = cutoff(moment, retention_days=retention_days)
    result = repository.prune(cutoff=boundary)
    repository.record_run(
        CollectionRun(
            run_id=f"prune-{uuid.uuid4().hex}",
            kind="prune",
            domain="intelligence",
            provider=None,
            started_at=moment,
            finished_at=moment,
            status="ok",
            deleted_count=result.total,
        )
    )
    log.info(
        "intelligence retention applied",
        extra=log_fields(
            cutoff=boundary.isoformat(),
            news=result.news,
            social=result.social,
            mentions=result.mentions,
        ),
    )
    return result


__all__ = ["RETENTION_DAYS", "cutoff", "is_within_retention", "prune"]
