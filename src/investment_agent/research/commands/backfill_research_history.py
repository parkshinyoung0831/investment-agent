"""과거 시점의 PIT 밸류에이션·feature를 주기적으로 쌓고, 끝난 구간에 label·학습 표본을 붙인다.

    python -m investment_agent.research.commands.backfill_research_history --start 2024-09-06 --every-days 28
    python -m investment_agent.research.commands.backfill_research_history --start 2024-09-06 --max-dates 4

매일 쌓는 live snapshot은 20거래일이 지나야 label이 붙는다. 그것만 기다리면 ML·RL은 한 달 가까이
학습 표본이 0이다. 과거 시점을 `historical_replay` 규칙(공시 다음날 00:00 NY 가용, 봉 확정 18:00 NY,
그날 S&P 멤버십, 거시·뉴스 제외)으로 재현하면 이미 끝난 구간의 label을 바로 만들 수 있다.

이미 snapshot이 있는 시점은 건너뛴다 — 중단 뒤 다시 실행해도 같은 시점을 두 번 계산하지 않는다.
backfill은 명시적 진입점이다. daily 하네스 job에 넣지 않는다.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Iterable

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

SOURCE_KIND = "historical_replay"
# 미국 일봉 확정(18:00 NY)을 서머타임과 무관하게 넘기는 UTC 시각.
_AS_OF_TIME = time(23, 30)
# label 구간(20거래일)이 끝나 확정될 때까지의 달력 여유.
_LABEL_SETTLE_DAYS = 35


def replay_dates(*, start: date, end: date, every_days: int) -> list[datetime]:
    """start부터 every_days 간격의 평일 판단 시각. 주말에 걸리면 직전 금요일로 당긴다."""
    if every_days < 1:
        raise ValueError("every_days must be positive")
    if end < start:
        raise ValueError("end must not precede start")
    output: list[datetime] = []
    cursor = start
    while cursor <= end:
        day = cursor - timedelta(days=max(0, cursor.weekday() - 4))
        moment = datetime.combine(day, _AS_OF_TIME, tzinfo=timezone.utc)
        if not output or moment > output[-1]:
            output.append(moment)
        cursor += timedelta(days=every_days)
    return output


def backfill(
    *,
    dates: Iterable[datetime],
    universe: Callable[[datetime], list[str]],
    has_snapshots: Callable[[datetime], bool],
    build_valuations: Callable[..., dict],
    build_features: Callable[..., dict],
    max_dates: int | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """시점마다 밸류에이션 → feature 순서로 적재한다. 이미 있는 시점은 건너뛴다."""
    results: list[dict[str, Any]] = []
    built = 0
    for as_of in dates:
        if has_snapshots(as_of):
            results.append({"as_of_at": as_of.isoformat(), "status": "skipped_existing"})
            continue
        if max_dates is not None and built >= max_dates:
            break
        tickers = universe(as_of)
        if not tickers:
            results.append({"as_of_at": as_of.isoformat(), "status": "no_membership"})
            continue
        valuations = build_valuations(as_of_at=as_of, tickers=tickers, source_kind=SOURCE_KIND, dry_run=dry_run)
        features = build_features(as_of_at=as_of, tickers=tickers, source_kind=SOURCE_KIND, dry_run=dry_run)
        built += 1
        results.append({
            "as_of_at": as_of.isoformat(),
            "status": "built",
            "tickers": len(tickers),
            "valuations": valuations.get("rows_upserted"),
            "features": features.get("rows_upserted"),
            "feature_status": features.get("status"),
        })
        log.info("historical replay date built %s", results[-1])
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.backfill_research_history")
    parser.add_argument("--start", required=True, help="첫 판단일 YYYY-MM-DD")
    parser.add_argument("--end", help="마지막 판단일. 기본은 label이 확정될 수 있는 가장 최근 날")
    parser.add_argument("--every-days", type=int, default=7)
    parser.add_argument("--max-dates", type=int, help="이번 실행에서 새로 만들 시점 수 상한")
    parser.add_argument("--skip-labels", action="store_true", help="label·표본 단계를 건너뛴다")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from investment_agent.research.commands.build_features import build_features
    from investment_agent.research.commands.build_labels import build_labels
    from investment_agent.research.commands.build_training_samples import build_training_samples
    from investment_agent.research.commands.build_valuations import build_valuations
    from investment_agent.research.datasets.universe import research_universe
    from investment_agent.research.storage.repository import ResearchStore
    from investment_agent.trading.decision.constants import SIGNAL_HORIZON_DAYS
    from investment_agent.trading.supabase_repository import SupabaseRepository

    now = datetime.now(timezone.utc)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else (now - timedelta(days=_LABEL_SETTLE_DAYS)).date()
    repository = SupabaseRepository()

    def has_snapshots(as_of: datetime) -> bool:
        rows = ResearchStore(read_only=True).records(
            "rl_feature_snapshots", start_as_of=as_of.isoformat(), end_as_of=as_of.isoformat(), limit=1,
        )
        return bool(rows)

    results = backfill(
        dates=replay_dates(start=start, end=end, every_days=args.every_days),
        universe=lambda as_of: research_universe(repository, as_of_at=as_of, source_kind=SOURCE_KIND),
        has_snapshots=has_snapshots,
        build_valuations=lambda **kwargs: build_valuations(repository=repository, **kwargs),
        build_features=lambda **kwargs: build_features(repository=repository, **kwargs),
        max_dates=args.max_dates,
        dry_run=args.dry_run,
    )
    log.info("historical replay dates built=%d skipped=%d",
             sum(row["status"] == "built" for row in results),
             sum(row["status"] == "skipped_existing" for row in results))
    if args.skip_labels or args.dry_run:
        return 0
    window_days = (now.date() - start).days + 7
    build_labels(as_of_at=now, horizon_days=SIGNAL_HORIZON_DAYS, lookback_days=window_days, repository=repository)
    build_training_samples(as_of_at=now, lookback_days=window_days, repository=repository)
    return 0


__all__ = ["backfill", "main", "replay_dates"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
