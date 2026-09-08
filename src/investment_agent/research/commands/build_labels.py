"""미래 구간이 끝난 feature snapshot에만 forward return label을 붙인다.

feature와 label을 물리적으로 분리한 계약을 지키는 유일한 생산 경로다. 미래 가격을
일부러 읽으므로 PIT 조회가 아니며, 구간이 아직 안 끝난 snapshot은 건드리지 않는다.
Research local dataset `rl_training_labels`의 identity가 (feature_version, as_of_at,
ticker)라서 한 snapshot당 horizon 하나만 저장된다 — 기본값은 현재 신호 계약과 같은
5거래일이다.
"""
from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from investment_agent.operations.runtime import run_log_payload
from investment_agent.platform.logging import get_logger
from investment_agent.trading.contracts import parse_datetime
from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.research.features.layer import FEATURE_VERSION, HORIZONS, FeatureLayer
from investment_agent.research.rl.contracts import RLSafetyError

log = get_logger(__name__)

WORKFLOW = "ai_investor_build_labels"
DEFAULT_BENCHMARK = "SPY"
_UPSERT_CHUNK = 100
# 미국 정규장 마감(16:00 ET)의 보수적 UTC 상한. 이 시각 이전을 label 확정 시점으로
# 주장하지 않으려고 쓴다. 실제 확정 시각은 적재 시각과 함께 max로 결정한다.
_SESSION_CLOSE_UTC_HOUR = 21


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.build_labels")
    parser.add_argument(
        "--horizon", type=int, default=5, choices=HORIZONS,
        help="label 구간의 거래일 수. 현재 신호 계약과 같은 5가 기본",
    )
    parser.add_argument(
        "--lookback-days", type=int, default=90,
        help="label을 찾을 snapshot as_of 창. 기본 90일",
    )
    parser.add_argument("--benchmark", default=DEFAULT_BENCHMARK, help="상대수익 기준 종목")
    parser.add_argument("--as-of", help="타임존을 포함한 ISO-8601 기준 시각. 기본은 현재 UTC")
    parser.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    return parser.parse_args(argv)


def _session_close(trade_date: str) -> datetime:
    """거래일 종가가 확정되는 보수적 시각을 UTC로 만든다.

    `market.prices_daily.trade_date`는 시각이 없는 DATE라 parse_datetime이 거부한다.
    여기서 마감 시각을 붙여 label 구간의 종료 시점을 명시적으로 만든다.
    """
    day = date.fromisoformat(str(trade_date)[:10])
    return datetime(
        day.year, day.month, day.day, _SESSION_CLOSE_UTC_HOUR, tzinfo=timezone.utc,
    )


def _closes_by_date(rows: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["trade_date"]): dict(row) for row in rows if row.get("close") is not None}


def build_labels(
    *,
    as_of_at: datetime,
    horizon_days: int,
    lookback_days: int,
    benchmark: str = DEFAULT_BENCHMARK,
    dry_run: bool = False,
    repository: SupabaseRepository | None = None,
) -> dict[str, object]:
    """구간이 확정된 snapshot에만 label을 만들어 저장한다."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    selected = repository or SupabaseRepository()
    window_start = (as_of_at - timedelta(days=lookback_days)).isoformat()
    window_end = as_of_at.isoformat()
    symbols = tuple(selected.current_tracked_tickers())
    if not symbols:
        raise RuntimeError("no tracked ticker is available for label building")

    snapshots = selected.rl_feature_snapshot_rows(
        symbols,
        start_as_of=window_start,
        end_as_of=window_end,
        feature_version=FEATURE_VERSION,
    )
    labeled = {
        (str(row["as_of_at"]), str(row["ticker"]))
        for row in selected.rl_training_label_rows(
            symbols,
            start_as_of=window_start,
            end_as_of=window_end,
            feature_version=FEATURE_VERSION,
            label_cutoff_at=window_end,
        )
    }

    # 벤치마크 종가는 종목마다 다시 읽지 않고 창 전체를 한 번만 읽는다.
    benchmark_rows = _closes_by_date(selected.forward_prices_for_labels(
        benchmark,
        after_date=(as_of_at - timedelta(days=lookback_days + 30)).date().isoformat(),
        limit=400,
    ))

    rows: list[dict] = []
    pending = skipped = 0
    failures: list[str] = []
    for snapshot_row in snapshots:
        key = (str(snapshot_row["as_of_at"]), str(snapshot_row["ticker"]))
        if key in labeled:
            continue
        ticker = str(snapshot_row["ticker"])
        snapshot_as_of = parse_datetime(str(snapshot_row["as_of_at"]))
        as_of_date = snapshot_as_of.date().isoformat()
        try:
            current = selected.market_prices(ticker, snapshot_as_of, limit=1)
            if not current or current[0].get("close") in (None, 0):
                skipped += 1
                continue
            forward = selected.forward_prices_for_labels(
                ticker, after_date=as_of_date, limit=horizon_days + 10
            )
            usable = [row for row in forward if row.get("close") not in (None, 0)]
            if len(usable) < horizon_days:
                # 구간이 아직 안 끝났다. 다음 실행이 다시 집는다.
                pending += 1
                continue
            end_row = usable[horizon_days - 1]
            end_date = str(end_row["trade_date"])
            benchmark_end = benchmark_rows.get(end_date)
            benchmark_start = _benchmark_close_at(selected, benchmark, snapshot_as_of)
            if benchmark_end is None or benchmark_start is None:
                skipped += 1
                continue
            forward_end_at = _session_close(end_date)
            ingested = end_row.get("ingested_at")
            # 종가 확정 시각보다 이르게 "알 수 있었다"고 주장하지 않는다.
            available_at = max(
                forward_end_at,
                parse_datetime(str(ingested)) if ingested else forward_end_at,
            )
            label = FeatureLayer.forward_label(
                feature_version=str(snapshot_row["feature_version"]),
                as_of_at=str(snapshot_row["as_of_at"]),
                ticker=ticker,
                horizon_days=horizon_days,
                current_close=float(current[0]["close"]),
                forward_close=float(end_row["close"]),
                benchmark_current_close=float(benchmark_start),
                benchmark_forward_close=float(benchmark_end["close"]),
                forward_end_at=forward_end_at.isoformat(),
                benchmark_forward_end_at=forward_end_at.isoformat(),
                label_available_at=available_at.isoformat(),
            )
        except (RLSafetyError, ValueError) as exc:
            log.warning("label build failed ticker=%s as_of=%s: %s", ticker, as_of_date, exc)
            failures.append(f"{ticker}@{as_of_date}")
            continue
        rows.append(label.to_storage_row())

    saved = 0
    if not dry_run:
        for start in range(0, len(rows), _UPSERT_CHUNK):
            chunk = rows[start:start + _UPSERT_CHUNK]
            selected.save_rl_training_labels(chunk)
            saved += len(chunk)

    payload = run_log_payload(
        workflow=WORKFLOW,
        status="success" if not failures else "partial",
        rows_upserted=saved,
        tickers_processed=len(snapshots),
        duration_sec=round(time.monotonic() - started, 3),
        started_at=started_at,
        detail={
            "feature_version": FEATURE_VERSION,
            "horizon_days": horizon_days,
            "benchmark": benchmark,
            "window": [window_start, window_end],
            "already_labeled": len(labeled),
            "built": len(rows),
            "pending_window_open": pending,
            "skipped_missing_price": skipped,
            "failed": failures[:20],
            "failed_count": len(failures),
            "dry_run": dry_run,
        },
    )
    log.info("forward labels %s", payload)
    return payload


def _benchmark_close_at(
    repository: SupabaseRepository,
    benchmark: str,
    as_of_at: datetime,
) -> float | None:
    """label 시작 시점의 벤치마크 종가는 PIT 경로로 읽는다."""
    rows = repository.market_prices(benchmark, as_of_at, limit=1)
    if not rows or rows[0].get("close") in (None, 0):
        return None
    return float(rows[0]["close"])


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.lookback_days < 1:
        raise SystemExit("--lookback-days must be positive")
    as_of_at = parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    payload = build_labels(
        as_of_at=as_of_at,
        horizon_days=args.horizon,
        lookback_days=args.lookback_days,
        benchmark=args.benchmark.upper(),
        dry_run=args.dry_run,
    )
    return 0 if payload["status"] == "success" else 1


__all__ = ["DEFAULT_BENCHMARK", "WORKFLOW", "build_labels", "main"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
