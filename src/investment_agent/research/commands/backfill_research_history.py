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
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Iterable

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

SOURCE_KIND = "historical_replay"
# 미국 일봉 확정(18:00 NY)을 서머타임과 무관하게 넘기는 UTC 시각.
_AS_OF_TIME = time(23, 30)
# label 구간(20거래일)이 끝나 확정될 때까지의 달력 여유.
_LABEL_SETTLE_DAYS = 35
BACKFILL_RUNS_DATASET = "historical_replay_runs"


@dataclass(frozen=True)
class BackfillDateState:
    """한 재현 시점에서 다시 계산하지 않아도 되는 ticker와 완료 여부."""

    completed: bool = False
    stored_tickers: frozenset[str] = frozenset()
    terminal_tickers: frozenset[str] = frozenset()
    unavailable_tickers: frozenset[str] = frozenset()


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


def audit_backfill(
    *,
    dates: Iterable[datetime],
    universe: Callable[[datetime], list[str]],
    date_state: Callable[[datetime, list[str]], BackfillDateState],
) -> list[dict[str, Any]]:
    """저장된 snapshot과 영구 불가 종목을 합쳐 재현 날짜별 완결성을 읽기 전용으로 점검한다."""
    rows: list[dict[str, Any]] = []
    for as_of in dates:
        expected = sorted({str(ticker).upper() for ticker in universe(as_of)})
        if not expected:
            rows.append({
                "as_of_at": as_of.isoformat(), "status": "no_membership",
                "expected_count": 0, "snapshot_count": 0, "unavailable_count": 0,
                "terminal_count": 0, "coverage": 0.0, "missing_tickers": [],
            })
            continue
        state = date_state(as_of, expected)
        expected_set = set(expected)
        stored = expected_set & set(state.stored_tickers)
        unavailable = expected_set & set(state.unavailable_tickers)
        terminal = expected_set & set(state.terminal_tickers)
        missing = sorted(expected_set - terminal)
        status = "completed" if not missing else (
            "inconsistent_completed" if state.completed else "incomplete"
        )
        rows.append({
            "as_of_at": as_of.isoformat(),
            "status": status,
            "expected_count": len(expected),
            "snapshot_count": len(stored),
            "unavailable_count": len(unavailable),
            "terminal_count": len(terminal),
            "coverage": round(len(terminal) / len(expected), 6),
            "missing_tickers": missing,
        })
    return rows


def backfill(
    *,
    dates: Iterable[datetime],
    universe: Callable[[datetime], list[str]],
    date_state: Callable[[datetime, list[str]], BackfillDateState],
    build_valuations: Callable[..., dict],
    build_features: Callable[..., dict],
    record_result: Callable[[datetime, list[str], dict[str, Any]], None] | None = None,
    max_dates: int | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """시점마다 밸류에이션 → feature 순서로 적재한다. 이미 있는 시점은 건너뛴다."""
    results: list[dict[str, Any]] = []
    built = 0
    for as_of in dates:
        if max_dates is not None and built >= max_dates:
            break
        tickers = universe(as_of)
        if not tickers:
            results.append({"as_of_at": as_of.isoformat(), "status": "no_membership"})
            continue
        state = date_state(as_of, tickers)
        if state.completed:
            results.append({"as_of_at": as_of.isoformat(), "status": "skipped_existing"})
            continue
        pending = [ticker for ticker in tickers if ticker not in state.terminal_tickers]
        if not pending:
            results.append({"as_of_at": as_of.isoformat(), "status": "skipped_existing"})
            continue
        valuations = build_valuations(as_of_at=as_of, tickers=pending, source_kind=SOURCE_KIND, dry_run=dry_run)
        features = build_features(as_of_at=as_of, tickers=pending, source_kind=SOURCE_KIND, dry_run=dry_run)
        built += 1
        result = {
            "as_of_at": as_of.isoformat(),
            "status": "built" if features.get("status") == "success" else "partial",
            "tickers": len(tickers),
            "resumed_tickers": len(pending),
            "valuations": valuations.get("rows_upserted"),
            "features": features.get("rows_upserted"),
            "feature_status": features.get("status"),
            "feature_detail": dict(features.get("detail") or {}),
        }
        results.append(result)
        if record_result is not None and not dry_run:
            record_result(as_of, tickers, result)
        log.info("historical replay date built %s", {key: value for key, value in result.items()
                                                      if key != "feature_detail"})
    return results


def _universe_hash(tickers: list[str]) -> str:
    normalized = sorted({str(ticker).upper() for ticker in tickers})
    return hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.backfill_research_history")
    parser.add_argument("--start", required=True, help="첫 판단일 YYYY-MM-DD")
    parser.add_argument("--end", help="마지막 판단일. 기본은 label이 확정될 수 있는 가장 최근 날")
    parser.add_argument("--every-days", type=int, default=7)
    parser.add_argument("--max-dates", type=int, help="이번 실행에서 새로 만들 시점 수 상한")
    parser.add_argument("--skip-labels", action="store_true", help="label·표본 단계를 건너뛴다")
    parser.add_argument("--audit-only", action="store_true", help="날짜별 완결성만 JSON으로 출력하고 쓰지 않는다")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from investment_agent.research.commands.build_features import build_features
    from investment_agent.research.commands.build_labels import build_labels
    from investment_agent.research.commands.build_training_samples import build_training_samples
    from investment_agent.research.commands.build_valuations import build_valuations
    from investment_agent.research.datasets.universe import research_universe
    from investment_agent.research.storage.repository import ResearchStore
    from investment_agent.forecasting import SIGNAL_HORIZON_DAYS
    from investment_agent.research.evidence.reader import PitReader

    now = datetime.now(timezone.utc)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else (now - timedelta(days=_LABEL_SETTLE_DAYS)).date()
    repository = PitReader()

    from investment_agent.research.features.layer import FEATURE_VERSION, FeatureLayer

    definition_hash = FeatureLayer().definition_hash
    states: dict[str, BackfillDateState] = {}

    def date_state(as_of: datetime, tickers: list[str]) -> BackfillDateState:
        point = as_of.isoformat()
        snapshots = ResearchStore(read_only=True).records(
            "rl_feature_snapshots", start_as_of=point, end_as_of=point,
        )
        stored = {
            str(row["ticker"]).upper() for row in snapshots
            if str(row.get("feature_version")) == FEATURE_VERSION
        }
        manifests = ResearchStore(read_only=True).records(
            BACKFILL_RUNS_DATASET, start_as_of=point, end_as_of=point,
        )
        expected_hash = _universe_hash(tickers)
        matching = next((row for row in reversed(manifests)
                         if row.get("feature_version") == FEATURE_VERSION
                         and row.get("definition_hash") == definition_hash
                         and row.get("universe_hash") == expected_hash), None)
        unavailable = {
            str(ticker).upper() for ticker in (matching or {}).get("unavailable_tickers", [])
        }
        state = BackfillDateState(
            completed=bool(
                matching and matching.get("status") == "completed"
                and {str(ticker).upper() for ticker in tickers} <= stored | unavailable
            ),
            stored_tickers=frozenset(stored),
            terminal_tickers=frozenset(stored | unavailable),
            unavailable_tickers=frozenset(unavailable),
        )
        states[point] = state
        return state

    def record_result(as_of: datetime, tickers: list[str], result: dict[str, Any]) -> None:
        point = as_of.isoformat()
        detail = dict(result.get("feature_detail") or {})
        previous = states.get(point, BackfillDateState())
        unavailable = sorted(previous.unavailable_tickers | {
            str(ticker).upper() for ticker in detail.get("unavailable_tickers", [])
        })
        failed = sorted({str(ticker).upper() for ticker in detail.get("failed", [])})
        status = "completed" if not failed and result.get("feature_status") == "success" else "partial"
        ResearchStore().upsert_records(BACKFILL_RUNS_DATASET, [{
            "record_key": f"{FEATURE_VERSION}:{point}",
            "as_of_at": point,
            "available_at": datetime.now(timezone.utc).isoformat(),
            "feature_version": FEATURE_VERSION,
            "definition_hash": definition_hash,
            "universe_hash": _universe_hash(tickers),
            "expected_tickers": sorted({str(ticker).upper() for ticker in tickers}),
            "expected_count": len({str(ticker).upper() for ticker in tickers}),
            "unavailable_tickers": unavailable,
            "failed_tickers": failed,
            "status": status,
        }], key="record_key")

    dates = replay_dates(start=start, end=end, every_days=args.every_days)
    resolve_universe = lambda as_of: research_universe(repository, as_of_at=as_of, source_kind=SOURCE_KIND)
    if args.audit_only:
        rows = audit_backfill(dates=dates, universe=resolve_universe, date_state=date_state)
        print(json.dumps({"dates": rows}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    results = backfill(
        dates=dates,
        universe=resolve_universe,
        date_state=date_state,
        build_valuations=lambda **kwargs: build_valuations(repository=repository, **kwargs),
        build_features=lambda **kwargs: build_features(repository=repository, **kwargs),
        record_result=record_result,
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


__all__ = [
    "BACKFILL_RUNS_DATASET", "BackfillDateState", "audit_backfill", "backfill", "main", "replay_dates",
]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
