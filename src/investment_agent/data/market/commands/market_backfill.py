"""Market history backfill for prices, splits, and dividends."""
from __future__ import annotations

import argparse

from investment_agent.operations.backfill import add_backfill_from_arg, resolve_backfill_window
from investment_agent.platform.logging import get_logger
from investment_agent.data.market import BACKFILL_YEARS
from investment_agent.data.market.commands.market_daily import (
    clean_price_row,
    extract_dividend_events,
    extract_split_events,
)

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.data.market.commands.market_backfill")
    add_backfill_from_arg(parser)
    parser.add_argument(
        "--scope",
        choices=("missing", "all-current"),
        default="missing",
        help=(
            "missing seeds only tickers with no rows; all-current re-fetches every "
            "current S&P 500 member to extend or repair existing history."
        ),
    )
    parser.add_argument(
        "--tickers",
        help="쉼표로 구분한 대상 ticker. 지정 시 --scope를 무시하고 해당 종목만 백필한다.",
    )
    return parser.parse_args(argv)


def _targets(scope: str, tickers: str | None = None, *, missing_loader, all_loader) -> list[str]:
    if tickers:
        return [t.strip().upper() for t in tickers.split(",") if t.strip()]
    return all_loader() if scope == "all-current" else missing_loader()


def _backfill_prices(lookback_days: int, scope: str, tickers: str | None = None) -> None:
    """시세 이력 백필 — 평시는 신규만, 수동 보수 시 현재 멤버 전체."""
    from investment_agent.data.market.persistence import (
        universe_missing_prices,
        universe_tracked,
        upsert_dividend_events,
        upsert_prices,
        upsert_split_events,
    )
    from investment_agent.data.market.infrastructure.sources.yahoo import download_ohlcv

    targets = _targets(
        scope,
        tickers,
        missing_loader=universe_missing_prices,
        all_loader=universe_tracked,
    )
    if not targets:
        log.info("시세 백필 대상 0건 — skip (scope=%s)", scope)
        return
    log.info(
        "시세 백필 대상: %d 티커 · scope=%s · lookback_days=%d",
        len(targets),
        scope,
        lookback_days,
    )
    raw_rows = download_ohlcv(targets, lookback_days=lookback_days)
    if not raw_rows:
        raise RuntimeError(
            f"yfinance 빈 응답 ({len(targets)} 티커) — 백필을 실패 처리합니다"
        )

    # 운영 DB용 compact 전에 provider 원본 일봉을 보존한다. archive가 실패하면
    # event/price write를 시작하지 않아, 복구할 수 없는 축소만 남기지 않는다.
    from investment_agent.data.market.infrastructure.archive import archive_daily_rows
    archive_daily_rows(raw_rows)

    split_events = extract_split_events(raw_rows)
    dividend_events = extract_dividend_events(raw_rows)
    clean_prices = [clean_price_row(r) for r in raw_rows]

    if split_events:
        upsert_split_events(split_events)
    if dividend_events:
        upsert_dividend_events(dividend_events)

    from investment_agent.data.market.domain.retention import compact_price_rows
    clean_prices = compact_price_rows(clean_prices)
    n = upsert_prices(clean_prices)
    log.info("✅ 시세 백필: %d rows (splits=%d, divs=%d) × %d 티커", n, len(split_events), len(dividend_events), len(targets))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    price_window = resolve_backfill_window(
        args.backfill_from,
        default_years=BACKFILL_YEARS,
    )
    _backfill_prices(price_window.days, args.scope, args.tickers)

    from investment_agent.data.market.domain.retention import prune_history
    prune_history(today=price_window.end)
    log.info("완료 ✅ (scope=%s)", args.scope)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
