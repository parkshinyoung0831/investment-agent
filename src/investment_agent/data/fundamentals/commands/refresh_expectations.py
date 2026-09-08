"""시장 예상치·발표 일정·애널리스트 커버리지를 갱신하는 canonical 잡."""
from __future__ import annotations

import argparse
import os
import time

from investment_agent.operations.runtime import elapsed_sec
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)

_MAX_WORKERS = 16


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def _worker_count(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= _MAX_WORKERS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {_MAX_WORKERS}")
    return parsed


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.data.fundamentals.commands.refresh_expectations")
    parser.add_argument(
        "--scope",
        choices=("watchlist", "all"),
        default="all",
        help="watchlist=관심종목만, all=추적 중인 전 종목(기본)",
    )
    parser.add_argument(
        "--tickers",
        help="쉼표로 구분한 종목 직접 지정. --scope보다 우선한다.",
    )
    parser.add_argument(
        "--collection-budget-sec",
        type=_nonnegative_float,
        default=25 * 60,
        help="전체 수집 예산 초. 초과하면 이번 스냅샷 묶음을 저장하지 않는다(0=해제).",
    )
    parser.add_argument(
        "--workers",
        type=_worker_count,
        default=_worker_count(os.environ.get("FUNDAMENTALS_EXPECTATIONS_WORKERS", "4")),
        help="동시 Yahoo ticker 수(1~16, 기본 4).",
    )
    return parser.parse_args(argv)


# Yahoo는 상시 레이트리밋을 건다 — 실패 한 건에 잡을 실패시키면 알림이 매일 울리고,
# 그러면 진짜 고장이 그 소음에 묻힌다.
#
# 실패 건수는 (종목 × 수집 단계) 단위라 종목 수로 나누면 단위가 어긋난다. 한 종목이
# 여러 단계 중 일부만 실패해도 나머지 행은 정상 적재된다. 그래서 게이트는 실패 수가
# 아니라 **실제로 얼마나 들어갔는지**로 판정한다.
MIN_ROWS_PER_TICKER = 1.0


def expectations_exit_code(
    *,
    rows: int,
    tickers: int,
    failures: int,
    min_rows_per_ticker: float = MIN_ROWS_PER_TICKER,
) -> int:
    """부분 성공은 성공, 붕괴한 실행만 실패로 돌린다.

    `failures`는 로그·판단 근거로만 받는다 — 게이트는 적재량이 정한다.
    """
    if tickers <= 0:
        return 0
    return 0 if (rows / tickers) >= min_rows_per_ticker else 1



def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    from investment_agent.data.fundamentals.infrastructure.supabase import expectations

    started_monotonic = time.monotonic()
    collection_budget_sec = args.collection_budget_sec or None
    from investment_agent.data.fundamentals.application.refresh_expectations import (
        refresh_expectations,
    )
    from investment_agent.data.fundamentals.infrastructure.yahoo_finance import consensus

    tracked = expectations.universe_tracked()
    if args.tickers:
        requested = {
            ticker.strip().upper()
            for ticker in args.tickers.split(",")
            if ticker.strip()
        }
        unknown = requested - set(tracked)
        if unknown:
            raise ValueError(
                "requested tickers are not tracked: "
                + ",".join(sorted(unknown))
            )
        tickers = sorted(requested)
    elif args.scope == "all":
        tickers = tracked
    else:
        tickers = expectations.watchlist_tickers()
    metrics = refresh_expectations(
        tickers,
        source=consensus,
        expectations_repository=expectations,
        collection_budget_sec=collection_budget_sec,
        max_workers=args.workers,
    )

    failures = metrics.get("failures") or []
    log.info(
        "expectations refresh done: scope=%s tickers=%d rows=%d failures=%d "
        "discarded=%s duration_sec=%.1f",
        args.scope,
        metrics.get("tickers", 0),
        metrics.get("rows", 0),
        len(failures),
        bool(metrics.get("discarded")),
        elapsed_sec(started_monotonic),
    )
    if failures:
        log.warning("expectations refresh partial: failures=%s", failures[:25])
    return expectations_exit_code(
        rows=int(metrics.get("rows", 0)),
        tickers=int(metrics.get("tickers", 0)),
        failures=len(failures),
    )


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())

