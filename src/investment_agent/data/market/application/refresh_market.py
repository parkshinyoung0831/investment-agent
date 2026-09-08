"""Yahoo 원천 가격을 v1 security identity로 변환해 적재한다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from investment_agent.data.market.domain.models import DailyBar, DividendEvent, SplitEvent
from investment_agent.data.market.repository import MarketRepository
from investment_agent.data.universe.repository import UniverseRepository
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class MarketRefreshResult:
    bars: int
    splits: int
    dividends: int
    tickers: int
    earliest_trade_date: date | None
    latest_trade_date: date | None


def refresh_market(db: Database, *, lookback_days: int) -> MarketRefreshResult:
    """완결된 일봉만 받고, ticker를 저장 직전에 security_id로 바꾼다."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    from investment_agent.data.market.infrastructure.sources.yahoo import download_ohlcv

    universe = UniverseRepository(db)
    market = MarketRepository(db)
    securities = universe.tracked_securities()
    ids = {security.ticker: security.security_id for security in securities}
    raw = download_ohlcv(sorted(ids), lookback_days)
    unknown = sorted({str(row["ticker"]) for row in raw} - set(ids))
    if unknown:
        raise RuntimeError(f"market source returned ticker outside tracked universe: {unknown[:10]}")
    bars = [DailyBar.from_row({**row, "security_id": ids[str(row["ticker"])]}) for row in raw]
    splits = [SplitEvent.from_row({
        "security_id": ids[str(row["ticker"])],
        "action_date": row["trade_date"],
        "split_ratio": row["split_ratio"],
        "source": row.get("source"),
    }) for row in raw if row.get("split_ratio") not in (None, 1, 1.0)]
    dividends = [DividendEvent.from_row({
        "security_id": ids[str(row["ticker"])],
        "ex_date": row["trade_date"],
        "div_amount": row["div_amount"],
        "source": row.get("source"),
    }) for row in raw if row.get("div_amount") not in (None, 0, 0.0)]
    written_bars = market.upsert_bars(bars)
    written_splits = market.upsert_splits(splits)
    written_dividends = market.upsert_dividends(dividends)
    dates = [bar.trade_date for bar in bars]
    result = MarketRefreshResult(
        written_bars, written_splits, written_dividends, len(ids),
        min(dates) if dates else None, max(dates) if dates else None,
    )
    log.info("market_refresh %s", result)
    return result


__all__ = ["MarketRefreshResult", "refresh_market"]
