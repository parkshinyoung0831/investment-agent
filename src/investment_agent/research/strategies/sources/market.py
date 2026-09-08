"""market owner가 적재한 일봉에서 전략용 월말 종가를 읽는다."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from investment_agent.data.market import persistence as market_prices
from investment_agent.research.strategies import MIN_MONTHS, TICKERS


def _last_complete_month_end(today: date | None = None) -> pd.Timestamp:
    """가장 최근에 끝난 달의 마지막 날 (KST 기준)."""
    if today is None:
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    return pd.Timestamp(today.replace(day=1) - pd.Timedelta(days=1))


def download_monthly_close(
    tickers: list[str] | None = None,
    *,
    period: str = "2y",
) -> pd.DataFrame:
    """완료된 최신 월까지 모든 요청 종목이 있는 월말 종가 표를 반환한다."""
    requested = [str(ticker).strip().upper() for ticker in (TICKERS if tickers is None else tickers)]
    if not requested or any(not ticker for ticker in requested):
        raise ValueError("strategy ticker list must not be empty")
    if len(requested) != len(set(requested)):
        raise ValueError("strategy ticker list contains duplicates")
    df = market_prices.monthly_close_history(requested, period=period).copy()
    missing_columns = sorted(set(requested) - set(df.columns))
    if missing_columns:
        raise RuntimeError("market strategy history omitted tickers: " + ", ".join(missing_columns))
    try:
        index = pd.DatetimeIndex(pd.to_datetime(df.index))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("market returned invalid monthly dates") from exc
    if index.tz is not None:
        index = index.tz_localize(None)
    df.index = index
    df = df.sort_index()

    cutoff = _last_complete_month_end()
    df = df.loc[df.index <= cutoff].dropna(how="all")
    if df.empty:
        raise RuntimeError("market has no completed monthly strategy bars")
    periods = df.index.to_period("M")
    if periods.has_duplicates:
        raise RuntimeError("market returned duplicate monthly strategy bars")
    df.index = periods.to_timestamp("M")
    expected_period = cutoff.to_period("M")
    incomplete: list[str] = []
    for ticker in requested:
        values = pd.to_numeric(df[ticker], errors="coerce")
        finite = values.dropna()
        if (
            len(finite) < MIN_MONTHS
            or finite.index[-1].to_period("M") != expected_period
            or not np.isfinite(finite.to_numpy(dtype=float)).all()
            or (finite <= 0).any()
        ):
            incomplete.append(ticker)
        df[ticker] = values
    if incomplete:
        raise RuntimeError(
            "market strategy history is missing, stale, or invalid for: " + ", ".join(incomplete)
        )
    today_kst = datetime.now(ZoneInfo("Asia/Seoul")).date()
    if df.index[-1].to_period("M") >= pd.Timestamp(today_kst).to_period("M"):
        raise RuntimeError("strategy history contains an incomplete current month")
    return df.loc[:, requested]
