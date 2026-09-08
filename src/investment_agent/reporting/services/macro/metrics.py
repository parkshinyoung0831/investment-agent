"""KIND_COMPUTE_MATRIX 기반 파생 지표 계산기.

소비자가 macro v1 observation read model로 받은 원값(raw) 구간에서 직접 계산한다 (ETL은 raw만 저장).
z: pct_change()의 365D 시간 기반 rolling (수익률 z, 가격 z 아님).
drawdown/rebound: price/fx/oscillator는 %, spread/rate는 bp (0 가로지름 안전).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

ZSCORE_WINDOW = "365D"        # 시간 기반 rolling(이동 통계) 창: 캘린더 365일. z·level_z·52주 고저 공통.
MA_WINDOWS    = (50, 200)

_KIND_MATRIX = {
    "price":      {"z": True,  "ma": True,  "hilo_pct": True,  "hilo_bps": False},
    "fx":         {"z": True,  "ma": False, "hilo_pct": True,  "hilo_bps": False},
    # 외국인 순매수는 음수를 오가 pct_change z가 깨진다 → 레벨 z 사용.
    "flow":       {"level_z": True, "ma": False, "hilo_pct": False, "hilo_bps": False},
    "oscillator": {"z": False, "ma": False, "hilo_pct": True,  "hilo_bps": False},
    "spread":     {"z": False, "ma": False, "hilo_pct": False, "hilo_bps": True},
    "rate":       {"z": False, "ma": False, "hilo_pct": False, "hilo_bps": True},
    # 레벨 기반: 수익률 z 대신 level_z. valuation엔 역사적 percentile 추가.
    "valuation":  {"level_z": True, "percentile": True, "hilo_pct": True},
    "ratio":      {"level_z": True, "hilo_pct": True},
}


def row_scalars(row: pd.Series) -> dict:
    """metrics DataFrame 한 행 → 스칼라 dict (NaN 제거·float 캐스팅).

    db.py가 마지막·직전 관측치를 metrics/prev_metrics로 환원할 때 쓰는 단일 SSOT.
    """
    return {k: float(v) for k, v in row.items() if pd.notna(v)}


def compute_metrics_series(s: pd.Series, kind: str) -> pd.DataFrame:
    """시계열 전 구간 metrics DataFrame. db.py가 마지막·직전 행을 metrics/prev_metrics로 환원."""
    s = s.dropna()
    if s.empty:
        return pd.DataFrame()
    flags = _KIND_MATRIX.get(kind, {})

    if not isinstance(s.index, pd.DatetimeIndex):
        s = pd.Series(s.values, index=pd.to_datetime(s.index))
    if not s.index.is_monotonic_increasing:
        s = s.sort_index()

    out = pd.DataFrame(index=s.index)

    if flags.get("z"):
        ret = s.pct_change()
        if ret.notna().sum() >= 30:
            mean = ret.rolling(ZSCORE_WINDOW, min_periods=30).mean()
            std  = ret.rolling(ZSCORE_WINDOW, min_periods=30).std()
            out["z"] = ((ret - mean) / std).replace([np.inf, -np.inf], np.nan)

    if flags.get("level_z"):
        lmean = s.rolling(ZSCORE_WINDOW, min_periods=30).mean()
        lstd  = s.rolling(ZSCORE_WINDOW, min_periods=30).std()
        out["level_z"] = ((s - lmean) / lstd).replace([np.inf, -np.inf], np.nan)
    if flags.get("percentile"):
        out["percentile"] = s.expanding(min_periods=30).apply(
            lambda w: (w <= w[-1]).mean() * 100, raw=True
        )

    if flags.get("ma"):
        for w in MA_WINDOWS:
            if len(s) >= w:
                out[f"ma{w}"] = s.rolling(w, min_periods=w).mean()

    needs_hilo = flags.get("hilo_pct") or flags.get("hilo_bps")
    if needs_hilo:
        hi = s.rolling(ZSCORE_WINDOW, min_periods=30).max()
        lo = s.rolling(ZSCORE_WINDOW, min_periods=30).min()
        out["high52"] = hi
        out["low52"]  = lo
        if flags.get("hilo_pct"):
            # % 단위 — price/fx/oscillator (분모 양수 전제)
            out["drawdown"] = (s / hi.replace(0, np.nan) - 1.0) * 100
            out["rebound"]  = (s / lo.replace(0, np.nan) - 1.0) * 100
        elif flags.get("hilo_bps"):
            # bp 단위 — spread/rate (0 가로지름 안전)
            out["drawdown_bps"] = (s - hi) * 100
            out["rebound_bps"]  = (s - lo) * 100

    return out
