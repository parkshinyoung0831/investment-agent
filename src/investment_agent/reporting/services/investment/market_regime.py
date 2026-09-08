"""시장 가격을 Dashboard용 regime read model로 투영한다."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from investment_agent.trading.decision.regime import build_market_regime


def build_live_regime_read_model(value: Any) -> dict[str, Any] | None:
    """SPY·QQQ·VIX 최근 가격으로 저장하지 않는 시장 국면 미리보기를 계산한다."""

    if not isinstance(value, pd.DataFrame) or value.empty:
        return None
    frame = value.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        if "Close" not in frame.columns.get_level_values(0):
            return None
        close = frame.xs("Close", axis=1, level=0)
    elif "Close" in frame.columns:
        close = frame[["Close"]].rename(columns={"Close": "SPY"})
    else:
        return None
    close.columns = [str(column).upper() for column in close.columns]
    close = close.apply(pd.to_numeric, errors="coerce").dropna(how="all")
    if "SPY" not in close or close["SPY"].dropna().size < 21:
        return None
    spy = close["SPY"].dropna()
    benchmark_return = float(spy.iloc[-1] / spy.iloc[-21] - 1.0)
    daily = spy.pct_change().dropna().tail(60)
    volatility = float(daily.std() * math.sqrt(252)) if len(daily) >= 10 else None
    rolling_peak = float(spy.tail(60).max())
    drawdown = float(max(0.0, 1.0 - float(spy.iloc[-1]) / rolling_peak)) if rolling_peak > 0 else None
    return_columns = [column for column in ("SPY", "QQQ") if column in close]
    returns = []
    for column in return_columns:
        series = close[column].dropna()
        if len(series) >= 21 and float(series.iloc[-21]) != 0.0:
            returns.append(float(series.iloc[-1] / series.iloc[-21] - 1.0))
    breadth = sum(item > 0 for item in returns) / len(returns) if returns else None
    dispersion = float(pd.Series(returns).std(ddof=0)) if len(returns) > 1 else None
    vix = close["^VIX"].dropna() if "^VIX" in close else pd.Series(dtype="float64")
    if not vix.empty:
        # VIX는 백분율 숫자이므로 비율로 변환해 regime 변동성 입력에 사용한다.
        volatility = float(vix.iloc[-1]) / 100.0
    as_of = pd.to_datetime(close.index[-1], utc=True).to_pydatetime()
    regime = build_market_regime(
        as_of,
        benchmark_return=benchmark_return,
        breadth=breadth,
        volatility=volatility,
        drawdown=drawdown,
        dispersion=dispersion,
        available_at=as_of,
        source_ids=("yfinance:SPY", "yfinance:QQQ", "yfinance:^VIX"),
    )
    return {
        "as_of_at": regime.as_of_at,
        "risk_state": regime.risk_state,
        "trend": regime.trend,
        "volatility_state": regime.volatility_state,
        "liquidity_state": regime.liquidity_state,
        "macro_state": regime.macro_state,
        "event_risk": regime.event_risk,
        "confidence": regime.confidence,
        "metadata": dict(regime.metadata),
    }


__all__ = ["build_live_regime_read_model"]
