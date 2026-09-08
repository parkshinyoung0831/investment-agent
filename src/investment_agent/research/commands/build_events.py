"""로컬 DuckDB에 쌓인 뉴스·소셜 원문을 사건과 학습용 feature로 압축해 ResearchStore에 남긴다.

원문 자체는 Supabase로 올리지 않는다(라이선스·용량). 올라가는 것은 사건 단위로 묶고
수치로 요약한 파생물뿐이다. 그래서 이 command가 로컬 원문 캐시와 Research local
dataset(`events`·`event_feature_snapshots`) 사이의 유일한 다리다.

FK 때문에 tracked universe 밖의 종목은 여기서 버린다 — 저장 단계에서 통째로 실패하면
그날 수집분 전부를 잃는다.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, Sequence

from investment_agent.operations.runtime import run_log_payload
from investment_agent.platform.logging import get_logger
from investment_agent.trading.contracts import parse_datetime
from investment_agent.trading.evidence.cache import LocalEvidenceCache
from investment_agent.trading.decision.contracts import Event, EventFeatureSnapshot
from investment_agent.research.features.event_intelligence import (
    NormalizedContent,
    extract_events,
    normalize_content,
    summarize_event_features,
)

log = get_logger(__name__)

WORKFLOW = "ai_investor_build_events"
DEFAULT_WINDOW_DAYS = 7


class EventRepository(Protocol):
    def save_events(self, events: Sequence[Event]) -> None: ...
    def save_event_features(self, snapshots: Sequence[EventFeatureSnapshot]) -> None: ...


def _normalized(rows: Sequence[dict[str, Any]]) -> tuple[list[NormalizedContent], int]:
    """행 하나가 계약을 어겨도 그 행만 버린다 — 배치 전체를 잃지 않는다."""
    items: list[NormalizedContent] = []
    skipped = 0
    for row in rows:
        try:
            items.append(normalize_content(row))
        except (TypeError, ValueError) as exc:
            skipped += 1
            log.warning("skipped unusable local content row: %s", exc)
    return items, skipped


def build_events(
    *,
    cache: LocalEvidenceCache,
    repository: EventRepository,
    as_of_at: str,
    tickers: Sequence[str],
    window_days: int = DEFAULT_WINDOW_DAYS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """cutoff 이전 원문만 읽어 사건을 만들고 종목별 feature snapshot을 남긴다."""
    as_of = parse_datetime(as_of_at)
    wanted = frozenset(str(value).upper().strip() for value in tickers if str(value).strip())
    rows = cache.iter_contents(
        since=(as_of - timedelta(days=window_days)).isoformat(),
        until=as_of.isoformat(),
    )
    items, skipped = _normalized(rows)
    events = tuple(
        event for event in extract_events(items, as_of_at=as_of.isoformat())
        # ticker가 없는 글로벌 뉴스는 FK가 NULL을 허용하므로 그대로 둔다.
        if event.ticker is None or event.ticker in wanted
    )
    covered = {event.ticker for event in events if event.ticker}
    snapshots = tuple(
        summarize_event_features(
            events, ticker=ticker, as_of_at=as_of.isoformat(), window_days=window_days
        )
        for ticker in sorted(covered)
    )
    if not dry_run:
        repository.save_events(events)
        repository.save_event_features(snapshots)
    return {
        "rows_read": len(rows),
        "rows_skipped": skipped,
        "events": len(events),
        "snapshots": len(snapshots),
        "tickers": sorted(covered),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.build_events")
    parser.add_argument("--as-of", help="타임존을 포함한 ISO-8601 기준 시각. 기본은 현재 UTC")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--cache-path", default=None, help="로컬 뉴스·소셜 DuckDB 경로")
    parser.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from investment_agent.trading.supabase_repository import SupabaseRepository

    args = _parse_args(argv)
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    as_of = args.as_of or started_at
    repository = SupabaseRepository()
    result = build_events(
        cache=LocalEvidenceCache(args.cache_path),
        repository=repository,
        as_of_at=as_of,
        tickers=repository.current_tracked_tickers(),
        window_days=args.window_days,
        dry_run=args.dry_run,
    )
    log.info("%s", run_log_payload(
        workflow=WORKFLOW,
        status="success",
        rows_upserted=result["events"] + result["snapshots"],
        tickers_processed=len(result["tickers"]),
        duration_sec=round(time.monotonic() - started, 3),
        started_at=started_at,
        detail={**result, "as_of_at": as_of, "dry_run": args.dry_run},
    ))
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
