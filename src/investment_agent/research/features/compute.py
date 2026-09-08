"""src/investment_agent/research/features/compute.py — RSI·MACD 직접 계산.

§5 공식 그대로:
  RSI(14)            : Wilder smoothing (alpha=1/14, adjust=False)
  MACD(12, 26, 9)    : EMA fast - EMA slow / signal=EMA(MACD,9) / hist=MACD-signal
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder RSI. 첫 length-1행은 NaN."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Wilder smoothing == EMA with alpha=1/length, adjust=False
    avg_gain = gain.ewm(alpha=1/length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1/length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi14 = 100.0 - 100.0 / (1.0 + rs)
    # 손실이 전혀 없는 구간(avg_loss=0)은 전통 정의상 RSI=100.
    # warmup 구간은 avg_loss가 NaN이라 마스킹 대상에서 제외되어 NaN 유지.
    rsi14 = rsi14.mask(avg_loss == 0.0, 100.0)
    return rsi14.rename("rsi14")


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line / signal. EMA는 adjust=False (전통 정의)."""
    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    sig = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({
        "macd":        macd_line,
        "macd_signal": sig,
    })


def compute_all(prices: pd.DataFrame) -> pd.DataFrame:
    """단일 ticker 가격을 날짜당 한 행의 저장형 지표로 계산한다.

    입력 컬럼: ticker · trade_date · close
    출력 컬럼: ticker · trade_date · rsi14 · macd · macd_signal
    BB·OBV·이동평균 등 이동창 지표는 저장하지 않고 뷰로 계산한다.
    macd_hist는 미산출 — 분석가가 필요 시 derive.
    """
    if prices.empty:
        return pd.DataFrame(
            columns=["ticker", "trade_date", "rsi14", "macd", "macd_signal"]
        )
    s   = prices.sort_values("trade_date").reset_index(drop=True)
    px  = s["close"].astype("float64")

    wide = pd.concat([
        s[["ticker", "trade_date"]],
        rsi(px),
        macd(px)[["macd", "macd_signal"]],
    ], axis=1)

    return wide.dropna(subset=["rsi14", "macd", "macd_signal"]).reset_index(drop=True)
