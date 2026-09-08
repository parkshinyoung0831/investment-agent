"""Core runner for technical indicators."""
from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd

from investment_agent.operations.runtime import elapsed_sec
from investment_agent.platform.logging import get_logger
from investment_agent.research.features import ROLLING_DAYS, STORAGE_DAYS, db
from investment_agent.research.features.compute import compute_all
from investment_agent.research.features.prices import load_prices

log = get_logger(__name__)

_DAILY_RECHECK_DAYS = 14


def run(
    *,
    rolling_days: int | None = None,
    workflow: str = "daily",
    force: bool = False,
    save_from: date | None = None,
) -> int:
    t0 = time.monotonic()
    latest_market = db.latest_market_date()
    latest_indicator = db.latest_indicator_date() if workflow == "daily" else None
    anchor_date = date.fromisoformat(latest_market) if latest_market else None
    effective_rolling_days = rolling_days or ROLLING_DAYS
    market_window_start = (
        anchor_date
        - timedelta(days=effective_rolling_days * 7 // 5 + 15)
        if anchor_date
        else None
    )
    dirty_market_date = None
    if workflow == "daily" and market_window_start:
        dirty_market_date = db.earliest_market_change_since(
            market_window_start.isoformat(),
            after_ingested_at=db.latest_indicator_write_at(),
        )
    prices = (
        load_prices(end_date=anchor_date)
        if rolling_days is None
        else load_prices(rolling_days=rolling_days, end_date=anchor_date)
    )
    if prices.empty:
        raise RuntimeError(f"no prices loaded for tech indicators workflow={workflow}")
    storage_anchor = anchor_date or max(prices["trade_date"])

    frames = [compute_all(g) for _, g in prices.groupby("ticker", sort=False)]
    indicators = pd.concat(frames, ignore_index=True)

    candidate_rows = len(indicators)
    if save_from is not None:
        indicators = indicators[
            pd.to_datetime(indicators["trade_date"]).dt.date >= save_from
        ].copy()
    if workflow == "daily":
        storage_floor = storage_anchor - timedelta(days=STORAGE_DAYS)
        if force or latest_indicator is None or anchor_date is None:
            save_start = max(prices["trade_date"].min(), storage_floor)
        else:
            price_floor = prices["trade_date"].min()
            overlap_start = max(
                price_floor,
                anchor_date - timedelta(days=_DAILY_RECHECK_DAYS),
            )
            candidates = [overlap_start]
            if dirty_market_date:
                candidates.append(date.fromisoformat(dirty_market_date))
            if latest_market and latest_market > latest_indicator:
                candidates.append(date.fromisoformat(latest_indicator) + timedelta(days=1))
            save_start = max(min(candidates), storage_floor)
        save_start_iso = save_start.isoformat()
        indicators = indicators[
            pd.to_datetime(indicators["trade_date"]).dt.date >= save_start
        ].copy()
        indicators = db.changed_indicators(
            indicators,
            db.existing_indicators_since(save_start_iso),
        )

    n = db.upsert_indicators(indicators)
    log.info(
        "research features %s done: price_rows=%d tickers=%d "
        "candidate_rows=%d writes=%d duration_sec=%.1f",
        workflow,
        len(prices),
        prices["ticker"].nunique(),
        candidate_rows,
        n,
        elapsed_sec(t0),
    )
    return n
