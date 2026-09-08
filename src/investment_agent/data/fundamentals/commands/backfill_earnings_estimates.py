"""Yahoo 발표 이력으로 EPS 예상치를 재구성해 저장하는 수동 백필 진입점."""
from __future__ import annotations

import argparse
import traceback

from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="investment_agent.data.fundamentals.commands.backfill_earnings_estimates"
    )
    parser.add_argument("--scope", choices=("all", "watchlist"), default="all")
    parser.add_argument("--tickers", help="쉼표로 구분한 종목 직접 지정. --scope보다 우선한다.")
    parser.add_argument("--request-gap-sec", type=float, default=0.3)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """명시적으로만 수행하는 역사 EPS 예상치 백필."""
    configure_logging()
    args = _parse_args(argv)
    if args.request_gap_sec < 0:
        log.error("request gap must be non-negative")
        return 1
    try:
        from investment_agent.data.fundamentals.application.backfill_earnings_estimates import (
            backfill_historical_eps_estimates,
        )
        from investment_agent.data.fundamentals.infrastructure.supabase import (
            earnings_events,
            expectations,
        )
        from investment_agent.data.fundamentals.infrastructure.yahoo_finance import reported_earnings

        if args.tickers:
            tickers = sorted({
                ticker.strip().upper()
                for ticker in args.tickers.split(",")
                if ticker.strip()
            })
        elif args.scope == "watchlist":
            tickers = expectations.watchlist_tickers()
        else:
            # 전체 범위는 이미 존재하는 속보 행만 읽어 요청 URL의 종목 목록을 비대하게 만들지 않는다.
            tickers = None

        metrics = backfill_historical_eps_estimates(
            tickers=tickers,
            flash_repository=earnings_events,
            expectations_repository=expectations,
            source=reported_earnings,
            request_gap_sec=args.request_gap_sec,
        )
        log.info("historical EPS estimate backfill complete metrics=%s", metrics)
        return 1 if metrics["failures"] else 0
    except Exception as exc:  # noqa: BLE001 - canonical CLI 경계
        log.error("historical EPS estimate backfill failed: %s\n%s", exc, traceback.format_exc())
        return 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
