"""저장된 market 가격으로 일별 breadth를 계산한다."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from investment_agent.data.macro.infrastructure.fetch import safe_fetch
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

SCHEMA = "market"
T_PRICES = "prices_daily"

_BREADTH_SERIES_ID = "BREADTH_200DMA"
_DEFAULT_MA_WINDOW = 200
_DEFAULT_MIN_PERIODS = 180
_DEFAULT_MIN_COVERAGE = 0.75


class MarketPriceReader:
    """Macro breadth가 소비하는 최소 Market 저장 interface."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def rows(
        self,
        security_ids: list[int],
        *,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        return self._db.select_in_chunks(
            schema=SCHEMA,
            table=T_PRICES,
            columns="security_id,trade_date,close",
            filter_column="security_id",
            values=[str(value) for value in security_ids],
            configure=lambda query: query.gte("trade_date", start.isoformat()).lte(
                "trade_date", end.isoformat()
            ),
            order_by="security_id,trade_date",
        )


def _breadth_config(indicator: dict) -> tuple[int, int, float]:
    params = indicator.get("source_params") or {}
    if not isinstance(params, dict):
        raise TypeError("source_params must be an object")
    try:
        ma_window = int(params.get("ma_window", _DEFAULT_MA_WINDOW))
        min_periods = int(params.get("min_periods", _DEFAULT_MIN_PERIODS))
        min_coverage = float(params.get("min_coverage", _DEFAULT_MIN_COVERAGE))
    except (TypeError, ValueError) as exc:
        raise ValueError("breadth calculation parameters must be numeric") from exc
    if ma_window < 1:
        raise ValueError("ma_window must be positive")
    if min_periods < 1 or min_periods > ma_window:
        raise ValueError("min_periods must be between 1 and ma_window")
    if not 0 < min_coverage <= 1:
        raise ValueError("min_coverage must be in (0, 1]")
    return ma_window, min_periods, min_coverage


def breadth_200dma(
    start: date,
    end: date,
    *,
    universe_repository,
    load_prices,
    ma_window: int = _DEFAULT_MA_WINDOW,
    min_periods: int = _DEFAULT_MIN_PERIODS,
    min_coverage: float = _DEFAULT_MIN_COVERAGE,
) -> pd.Series:
    """S&P 500 현재 구성종목 중 200일선 위에 있는 비율을 반환한다.

    RPC가 실패해도 같은 가격 테이블을 REST로 계산한다. 두 경로 모두 충분한
    구성종목과 가격 이력이 없으면 값을 만들지 않는다.
    """
    membership = universe_repository.latest_membership()
    if membership is None or not membership.tickers:
        raise ValueError("universe S&P 500 membership snapshot is empty")
    securities = universe_repository.securities_by_ticker(membership.tickers)
    tracked = {ticker: security.security_id for ticker, security in securities.items()}
    if not tracked:
        raise ValueError("universe S&P 500 membership has no securities")

    fetch_start = start - timedelta(days=ma_window + 120)
    bars = load_prices(
        list(tracked.values()), start=fetch_start, end=end,
    )
    if not bars:
        raise ValueError("market price history is empty for the breadth window")

    security_to_ticker = {security.security_id: ticker for ticker, security in securities.items()}
    frame = pd.DataFrame([
        {
            "trade_date": bar["trade_date"],
            "ticker": security_to_ticker.get(int(bar["security_id"])),
            "close": bar["close"],
        }
        for bar in bars
    ])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame[frame["ticker"].notna()]
    frame = frame.dropna(subset=["trade_date", "close"])
    if frame.empty:
        raise ValueError("market price history has no usable closes")

    close = (
        frame.pivot_table(
            index="trade_date",
            columns="ticker",
            values="close",
            aggfunc="last",
        )
        .sort_index()
    )
    moving_average = close.rolling(ma_window, min_periods=min_periods).mean()
    eligible = close.notna() & moving_average.notna()
    eligible_count = eligible.sum(axis=1)
    minimum_members = max(1, int(len(tracked) * min_coverage))
    breadth = (
        ((close > moving_average) & eligible).sum(axis=1)
        / eligible_count.where(eligible_count > 0)
        * 100.0
    )
    breadth = breadth[
        (breadth.index >= pd.Timestamp(start))
        & (eligible_count >= minimum_members)
    ].dropna().sort_index()
    if breadth.empty:
        raise ValueError(
            f"not enough market history for breadth: need >= {minimum_members} eligible members"
        )

    log.info(
        "market breadth computed: %d dates, last=%s %.2f%%",
        len(breadth),
        breadth.index[-1].date(),
        float(breadth.iloc[-1]),
    )
    return breadth


def fetch_batch(
    indicators: list[dict],
    start: date,
    end: date,
    *,
    universe_repository=None,
    load_prices=None,
) -> tuple[dict[str, pd.Series], list[dict]]:
    """market 스키마 입력을 사용하는 MACRO series를 수집한다."""
    if start > end:
        raise ValueError("start must be on or before end")
    if universe_repository is None or load_prices is None:
        raise ValueError("market breadth requires universe identity and market price readers")

    def fetch_one(indicator: dict) -> pd.Series:
        if str(indicator.get("series_id")) != _BREADTH_SERIES_ID:
            raise ValueError(
                f"unsupported market series: {indicator.get('series_id')}"
            )
        ma_window, min_periods, min_coverage = _breadth_config(indicator)
        return breadth_200dma(
            start,
            end,
            universe_repository=universe_repository,
            load_prices=load_prices,
            ma_window=ma_window,
            min_periods=min_periods,
            min_coverage=min_coverage,
        )

    return safe_fetch(log, indicators, fetch_one)
