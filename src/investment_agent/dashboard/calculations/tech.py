"""대시보드 기술적 지표 계산."""
from __future__ import annotations

import numpy as np
import pandas as pd

from investment_agent.research.features.compute import rsi as wilder_rsi

def add_technical_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """OHLC 프레임 복사본에 ``SMA20``, ``SMA60``, ``RSI14``를 추가한다.

    종가는 ``Close`` 또는 ``close`` 컬럼에서 읽는다. 종가가 없거나 유한하지 않은
    구간은 0으로 채우지 않고 ``NaN``으로 유지한다. RSI는 저장 기술지표 계산과
    동일한 Wilder smoothing 구현을 재사용한다.
    """
    if not isinstance(frame, pd.DataFrame):
        return pd.DataFrame(columns=["SMA20", "SMA60", "RSI14"])
    result = frame.copy(deep=True)
    close_column = next((name for name in ("Close", "close") if name in result.columns), None)
    if close_column is None:
        result["SMA20"] = np.nan
        result["SMA60"] = np.nan
        result["RSI14"] = np.nan
        return result

    close = pd.to_numeric(result[close_column], errors="coerce").astype("float64")
    close = close.where(np.isfinite(close), np.nan)
    result["SMA20"] = close.rolling(window=20, min_periods=20).mean()
    result["SMA60"] = close.rolling(window=60, min_periods=60).mean()
    result["RSI14"] = wilder_rsi(close, length=14)
    return result
