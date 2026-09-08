"""고정 IP 환경에서 토스 보유종목을 Supabase 관심종목과 동기화한다."""
from __future__ import annotations

import argparse
import time

from investment_agent.data.universe.watchlists.toss_sync import sync_toss_holdings
from investment_agent.operations.runtime import elapsed_sec
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="investment_agent.data.universe.watchlists.toss_holdings")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="토스 조회·변환만 수행하고 Supabase는 변경하지 않음",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parser().parse_args(argv)
    started = time.monotonic()
    result = sync_toss_holdings(dry_run=args.dry_run)
    skipped = result.get("skipped_tickers") or []
    log.info(
        "toss holdings sync done accounts=%d holding_items=%d us_tickers=%d "
        "added=%d removed=%d skipped=%d dry_run=%s duration_sec=%.1f",
        result.get("accounts", 0),
        result.get("holding_items", 0),
        result.get("us_tickers", 0),
        result.get("added", 0),
        result.get("removed", 0),
        len(skipped),
        args.dry_run,
        elapsed_sec(started),
    )
    if skipped:
        log.warning(
            "현재 수집 대상(S&P 500)이 아니라 제외된 토스 보유종목: %s",
            ",".join(str(ticker) for ticker in skipped),
        )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())

