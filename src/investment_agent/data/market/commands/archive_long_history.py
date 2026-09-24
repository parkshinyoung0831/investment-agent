"""과거 S&P 500 멤버의 긴 일봉 이력을 로컬 archive에만 받는다.

운영 DB(`market.prices_daily`)의 가격 이력은 적재했던 백필 창만큼이다(지금 2019-09부터). 과거 재현·ML 학습은
그보다 긴 이력이 필요하다. Supabase Free 용량을 쓰지 않도록 provider 원본을
`market_history/yahoo/<security_id>/daily.parquet`에 받아 두고
로컬 사본(`local_mirror`)이 운영 DB 창보다 오래된 날짜를 거기서 채운다. **Supabase에 쓰지 않는다.**

대상은 로컬 사본의 멤버십 구간 전체(2015-03 이후 S&P 500에 한 번이라도 들었던 종목)와 참조 ETF다.
상장폐지·인수된 종목은 provider가 이력을 주지 않는다 — 실패가 아니라 `unavailable`로 센다.
"""
from __future__ import annotations

import argparse
from datetime import date

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

DEFAULT_START = date(2014, 1, 2)


def _targets() -> list[tuple[int, str]]:
    """(security_id, 조회 ticker). 개명 종목은 지금 이름으로 조회한다."""
    from investment_agent.data.market import REFERENCE_PRICE_TICKERS
    from investment_agent.data.market.local_mirror.store import LocalMirror
    from investment_agent.data.universe.domain.ticker_renames import HISTORICAL_TICKER_RENAMES

    mirror = LocalMirror()
    memberships = mirror.frame("memberships")
    securities = mirror.frame("securities")
    targets = {int(row.security_id): HISTORICAL_TICKER_RENAMES.get(str(row.ticker), str(row.ticker))
               for row in memberships.itertuples()}
    reference = securities[securities["ticker"].isin(list(REFERENCE_PRICE_TICKERS))
                           & securities["is_active_listing"].fillna(False)]
    for row in reference.itertuples():
        targets.setdefault(int(row.security_id), str(row.ticker))
    return sorted(targets.items(), key=lambda item: item[1])


def archive_long_history(*, start: date, tickers: set[str] | None = None) -> dict[str, int]:
    from investment_agent.data.market.application.price_collection import PriceTarget, collect_prices
    from investment_agent.data.market.infrastructure.archive import archive_daily_rows
    from investment_agent.data.market.infrastructure.sources.yahoo import download_ohlcv
    from investment_agent.platform.clock import us_market_today

    lookback_days = (us_market_today() - start).days
    counts = {"archived": 0, "unavailable": 0, "rows": 0}
    for security_id, ticker in _targets():
        if tickers is not None and ticker not in tickers:
            continue
        try:
            batch = collect_prices([PriceTarget(security_id, ticker)], lookback_days=lookback_days,
                                   download=download_ohlcv, archive=archive_daily_rows)
        except RuntimeError as exc:
            # 상장폐지·인수 종목은 provider에 이력이 없다. 다음 종목으로 간다.
            counts["unavailable"] += 1
            log.info("long history unavailable ticker=%s security_id=%s: %s", ticker, security_id, str(exc)[:160])
            continue
        counts["archived"] += 1
        counts["rows"] += batch.raw_rows
    log.info("long history archived %s", counts)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.data.market.commands.archive_long_history")
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START,
                        help="받을 첫 날짜(YYYY-MM-DD). 기본은 멤버십 이력 시작 전 1년 warmup")
    parser.add_argument("--tickers", help="쉼표로 구분한 대상 ticker. 기본은 멤버십 전체 + 참조 ETF")
    args = parser.parse_args(argv)
    wanted = {value.strip().upper() for value in args.tickers.split(",") if value.strip()} if args.tickers else None
    archive_long_history(start=args.start, tickers=wanted)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
