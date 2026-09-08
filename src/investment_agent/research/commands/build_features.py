"""tracked universe의 PIT feature snapshot을 매일 ResearchStore에 적재한다.

이 command가 없으면 Research local dataset `rl_feature_snapshots`가 비어 있고, ML/RL은
학습할 dataset 자체를 만들 수 없다. LLM 호출도 주문도 하지 않는 순수 계산 잡이라
거래 kill switch와 무관하게 돈다.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone

from investment_agent.operations.runtime import run_log_payload
from investment_agent.platform.logging import get_logger
from investment_agent.trading.evidence.context import ContextBuilder
from investment_agent.trading.contracts import parse_datetime
from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.research.features.layer import FEATURE_VERSION, FeatureLayer

log = get_logger(__name__)

WORKFLOW = "ai_investor_build_features"
# PostgREST payload가 지나치게 커지지 않도록 upsert를 나눈다.
_UPSERT_CHUNK = 100
# 밸류에이션 관측값을 찾을 창. 공시가 없는 날에도 직전 값을 쓴다.
_VALUATION_LOOKBACK_DAYS = 7


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.build_features")
    parser.add_argument("--ticker", action="append", help="지정 종목만 실행. 여러 번 사용 가능")
    parser.add_argument("--limit", type=int, help="처리할 최대 종목 수. 기본은 전체 tracked")
    parser.add_argument("--as-of", help="타임존을 포함한 ISO-8601 기준 시각. 기본은 현재 UTC")
    parser.add_argument(
        "--source-kind",
        choices=("live_shadow", "historical_replay"),
        default="live_shadow",
        help="historical_replay는 macro를 제외하고 news/social을 항상 차단한다",
    )
    parser.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    return parser.parse_args(argv)


def _valuations_by_ticker(
    repository: SupabaseRepository,
    *,
    as_of_at: datetime,
    tickers: list[str],
    source_kind: str,
) -> dict[str, dict]:
    """그 실행 시각까지의 최신 PIT 밸류에이션 관측값을 종목별로 고른다.

    원장이 아직 비어 있거나 조회가 실패해도 feature 적재 자체는 막지 않는다 —
    밸류에이션 컬럼만 결측으로 남고 `__is_missing` 지표가 그 사실을 기록한다.
    """
    if not hasattr(repository, "valuation_observation_rows"):
        return {}
    try:
        rows = repository.valuation_observation_rows(
            tuple(tickers),
            start_as_of=(as_of_at - timedelta(days=_VALUATION_LOOKBACK_DAYS)).isoformat(),
            end_as_of=as_of_at.isoformat(),
            source_kind=source_kind,
        )
    except Exception as exc:  # 원장 미적용·조회 실패가 그날 수집을 멈추지 않는다.
        log.warning("valuation observations unavailable: %s", exc)
        return {}
    latest: dict[str, dict] = {}
    for row in sorted(rows, key=lambda item: str(item.get("as_of_at") or "")):
        latest[str(row["ticker"])] = dict(row)
    return latest


def build_features(
    *,
    as_of_at: datetime,
    tickers: list[str],
    source_kind: str = "live_shadow",
    dry_run: bool = False,
    repository: SupabaseRepository | None = None,
) -> dict[str, object]:
    """종목별 EvidenceBundle을 고정 스키마 FeatureSnapshot으로 바꿔 저장한다."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    selected = repository or SupabaseRepository()
    builder = ContextBuilder(selected)
    layer = FeatureLayer()
    # 같은 실행 시각의 밸류에이션 관측값을 한 번만 읽어 종목별로 나눠 쓴다.
    # 하네스는 build_valuations를 먼저 돌리므로 그날 값이 이미 들어와 있다.
    valuations = _valuations_by_ticker(
        selected, as_of_at=as_of_at, tickers=tickers, source_kind=source_kind,
    )
    rows: list[dict] = []
    failures: list[str] = []
    unavailable = 0
    for ticker in tickers:
        try:
            bundle = builder.build(ticker, as_of_at, source_kind=source_kind)
            snapshot = layer.build(bundle, valuation=valuations.get(ticker)).snapshot
        except Exception as exc:  # 한 종목 실패가 그날 전체 수집을 막지 않는다.
            log.warning("feature build failed ticker=%s: %s", ticker, exc)
            failures.append(ticker)
            continue
        if not snapshot.is_available:
            # 근거가 하나도 없으면 저장해도 학습에 쓸 수 없다. 결측 사유는 로그로만 남긴다.
            unavailable += 1
            continue
        rows.append(snapshot.to_storage_row())

    saved = 0
    if not dry_run:
        for start in range(0, len(rows), _UPSERT_CHUNK):
            chunk = rows[start:start + _UPSERT_CHUNK]
            selected.save_rl_feature_snapshots(chunk)
            saved += len(chunk)

    payload = run_log_payload(
        workflow=WORKFLOW,
        status="success" if not failures else "partial",
        rows_upserted=saved,
        tickers_processed=len(tickers),
        duration_sec=round(time.monotonic() - started, 3),
        started_at=started_at,
        detail={
            "feature_version": FEATURE_VERSION,
            "definition_hash": layer.definition_hash,
            "as_of_at": as_of_at.isoformat(),
            "source_kind": source_kind,
            "built": len(rows),
            "with_valuation": sum(1 for ticker in tickers if ticker in valuations),
            "unavailable": unavailable,
            "failed": failures[:20],
            "failed_count": len(failures),
            "dry_run": dry_run,
        },
    )
    log.info("feature snapshots %s", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")
    as_of_at = parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    repository = SupabaseRepository()
    tickers = [value.upper() for value in (args.ticker or [])] or repository.current_tracked_tickers()
    if args.limit is not None:
        tickers = tickers[:args.limit]
    if not tickers:
        log.error("no tracked ticker is available for feature building")
        return 1
    payload = build_features(
        as_of_at=as_of_at,
        tickers=tickers,
        source_kind=args.source_kind,
        dry_run=args.dry_run,
        repository=repository,
    )
    return 0 if payload["status"] == "success" else 1


__all__ = ["WORKFLOW", "build_features", "main"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
