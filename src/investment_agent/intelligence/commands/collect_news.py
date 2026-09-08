"""관심종목 뉴스를 수집해 intelligence.duckdb에 적재한다."""
from __future__ import annotations

import argparse
import json
import sys

from investment_agent.intelligence.repository import IntelligenceRepository
from investment_agent.intelligence.application import collect_news as service
from investment_agent.intelligence.infrastructure.sources.news.yfinance import fetch_ticker_news
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="관심종목 뉴스 수집")
    parser.add_argument("--ticker", action="append", default=None, help="반복 지정 가능")
    parser.add_argument("--limit", type=int, default=20, help="종목당 최대 기사 수")
    parser.add_argument("--dry-run", action="store_true", help="적재 없이 대상만 보고")
    args = parser.parse_args(argv)

    configure_logging()
    tickers = [t.upper() for t in (args.ticker or [])] or service.watchlist_tickers()
    if args.dry_run:
        print(json.dumps({"tickers": tickers, "count": len(tickers)}, ensure_ascii=False))
        return 0

    run = service.collect_news(
        repository=IntelligenceRepository(),
        fetch=lambda ticker: fetch_ticker_news(ticker, limit=args.limit),
        tickers=tickers,
    )
    print(
        json.dumps(
            {
                "run_id": run.run_id,
                "status": run.status,
                "stored": run.stored_count,
                "duplicates": run.duplicate_count,
                "unparsed": run.unparsed_count,
            },
            ensure_ascii=False,
        )
    )
    return 0 if run.status in {"ok", "partial", "capped"} else 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli

    start_cli()
    sys.exit(main())
