"""최근 Item 2.02 실적 발표 이벤트를 갱신하는 canonical 잡."""
from __future__ import annotations

import argparse
import traceback

from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="investment_agent.data.fundamentals.commands.refresh_earnings_events"
    )
    parser.add_argument(
        "--scope",
        choices=("watchlist", "all"),
        default="watchlist",
    )
    parser.add_argument(
        "--tickers",
        help="쉼표로 구분한 종목 직접 지정. --scope보다 우선한다.",
    )
    parser.add_argument("--cutoff-days", type=int, default=14)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    try:
        from investment_agent.data.fundamentals.application.detect_earnings_events import (
            detect_earnings_events,
        )
        from investment_agent.data.fundamentals.infrastructure.sec import companyfacts
        from investment_agent.data.fundamentals.infrastructure.sec import press_releases
        from investment_agent.data.fundamentals.infrastructure.supabase import (
            company_financials,
            earnings_events,
        )
        from investment_agent.data.fundamentals.infrastructure.yahoo_finance import reported_earnings

        ticker_to_cik = {
            str(ticker).upper(): str(cik).zfill(10)
            for cik, tickers in company_financials.tickers_by_cik().items()
            for ticker in tickers
        }
        if args.tickers:
            selected = sorted({
                ticker.strip().upper()
                for ticker in args.tickers.split(",")
                if ticker.strip()
            })
        elif args.scope == "all":
            selected = sorted(ticker_to_cik)
        else:
            selected = sorted(company_financials.watchlist_tickers())

        missing = [ticker for ticker in selected if ticker not in ticker_to_cik]
        targets = [
            (ticker, ticker_to_cik[ticker])
            for ticker in selected
            if ticker in ticker_to_cik
        ]
        metrics = detect_earnings_events(
            targets,
            filing_source=companyfacts,
            reported_source=reported_earnings,
            press_release_source=press_releases,
            repository=earnings_events,
            cutoff_days=args.cutoff_days,
        )
        metrics["failures"].extend(
            {"ticker": ticker, "error": "tracked CIK is missing"}
            for ticker in missing
        )
        log.info("earnings events refresh complete metrics=%s", metrics)
        return 1 if metrics["failures"] else 0
    except Exception as exc:  # noqa: BLE001 - canonical CLI 경계
        log.error("earnings events refresh failed: %s\n%s", exc, traceback.format_exc())
        return 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
