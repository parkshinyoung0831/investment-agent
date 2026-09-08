"""지표가 '경고할 수준'인지 판단(judgment)하는 곳 — 표시(format)는 format.py.

핵심은 eval_row(행): 그 지표가 빨강/노랑/초록 중 어디인지 정한다. core·watch가 같은 함수를 쓴다.
경보 임계(THRESHOLDS 맵)의 SSOT — 종목별 판단은 DB가 아니라 이 코드가 소유한다.
표시용 분류·색상은 constants.py, 숫자·배지 꾸미기는 format.py.
"""
from __future__ import annotations
from typing import Any

# 등급 비교용 내부 값.
_TIER_RANK = {"🟢 watch": 1, "🟡 caution": 2, "🔴 alert": 3}
_EMOJI = {"alert": "🔴 alert", "caution": "🟡 caution", "watch": "🟢 watch"}


# 경보 임계(THRESHOLDS). series_kind 기본 밴드 + series_id 개별 밴드.
# 밴드는 [lo, hi] 양방향, None=해당 방향 비활성.
_Z_STD = {
    "watch":   [-1.8, 1.8],
    "caution": [-2.0, 2.0],
    "alert":   [-3.0, 3.0],
}
_DRAWDOWN_STD = {
    "watch":   [-10.0, None],
    "caution": [-20.0, None],
    "alert":   [-30.0, None],
}
_REBOUND_STD = {
    "watch":   [None, 10.0],
    "caution": [None, 20.0],
    "alert":   [None, 30.0],
}
_DAILY_CHANGE_RATE = {
    "watch":   [-0.10, 0.10],
    "caution": [-0.20, 0.20],
    "alert":   [-0.30, 0.30],
}
# 레벨 z (level_z). 가격이 아니라 '레벨 자체'가 평소 대비 얼마나 높은가 — 밸류에이션·비율용.
_LEVEL_Z_STD = {
    "watch":   [-1.8, 1.8],
    "caution": [-2.0, 2.0],
    "alert":   [-3.0, 3.0],
}
# 역사적 백분위 (percentile, 0~100). 현재 값이 역사적으로 비싼/싼 구간인가 — 밸류에이션용.
_PERCENTILE_STD = {
    "watch":   [20, 80],
    "caution": [10, 90],
    "alert":   [5, 95],
}

# series_kind 기본 임계 (price/fx/flow + 레벨 기반 valuation/ratio). 그 외 kind는 개별 지정만 적용.
# metrics.py _KIND_MATRIX가 계산하는 지표와 짝이 맞아야 한다:
#   price/fx → z + drawdown/rebound, flow → level_z, valuation → level_z + percentile, ratio → level_z.
# flow(KR_FOREIGN_NET)는 음수를 오가서 수익률 z가 깨진다 → 레벨 z 사용 (metrics.py와 짝).
_KIND_THRESHOLDS: dict[str, dict] = {
    "price":     {"zscore": _Z_STD, "drawdown": _DRAWDOWN_STD, "rebound": _REBOUND_STD},
    "fx":        {"zscore": _Z_STD, "drawdown": _DRAWDOWN_STD, "rebound": _REBOUND_STD},
    "flow":      {"level_z": _LEVEL_Z_STD},
    "valuation": {"level_z": _LEVEL_Z_STD, "percentile": _PERCENTILE_STD},
    "ratio":     {"level_z": _LEVEL_Z_STD},
}

# series_id 개별 임계 (kind 기본 위에 병합 — 개별이 우선).
_SERIES_THRESHOLDS: dict[str, dict] = {
    "VIX":        {"value": {"watch": [None, 18],  "caution": [None, 25],  "alert": [None, 35]}},
    "MOVE":       {"value": {"watch": [None, 110], "caution": [None, 130], "alert": [None, 160]}},
    "FEAR_GREED": {"value": {"watch": [30, 70],    "caution": [20, 80],    "alert": [10, 90]}},
    "HY_SPREAD":  {"value": {"watch": [None, 4.5], "caution": [None, 6.0], "alert": [None, 8.0]}},
    "SPREAD_10Y2Y": {
        "value":        {"watch": [0.0, None], "caution": [-0.5, None], "alert": [-1.0, None]},
        "daily_change": _DAILY_CHANGE_RATE,
    },
    "SPREAD_10Y3M": {
        "value":        {"watch": [0.0, None], "caution": [-0.5, None], "alert": [-1.0, None]},
        "daily_change": _DAILY_CHANGE_RATE,
    },
    "US02Y": {"daily_change": _DAILY_CHANGE_RATE},
    "TNX":   {"daily_change": _DAILY_CHANGE_RATE},
    "TYX":   {"daily_change": _DAILY_CHANGE_RATE},
}


def thresholds_for(r: dict[str, Any]) -> dict:
    """행의 series_kind 기본 임계 + series_id 개별 임계를 병합해 돌려준다 (개별 우선).

    정의 SSOT는 위 두 맵이다.
    """
    merged = dict(_KIND_THRESHOLDS.get(r.get("series_kind") or "", {}))
    merged.update(_SERIES_THRESHOLDS.get(r.get("series_id") or "", {}))
    return merged


def stronger(a, b):
    """두 경고 등급 중 더 센 쪽을 고른다 (없는 값은 무시)."""
    if a is None:
        return b
    if b is None:
        return a
    return a if _TIER_RANK[a] >= _TIER_RANK[b] else b


# ── 국가 ────────────────────────────────────────────────────────────────────
# ── 경고 수준 판단 함수들 ────────────────────────────────────────────────
def _check_band(value, band):
    """값이 정해 둔 하한 이하이거나 상한 이상이면 '해당함(True)'."""
    if value is None or not band:
        return False
    lo, hi = band[0], band[1]
    if lo is not None and float(value) <= float(lo):
        return True
    if hi is not None and float(value) >= float(hi):
        return True
    return False


def _check_signed(value, band):
    """하락폭·반등폭처럼 부호가 중요한 값을 판단한다 (크기만 비교하거나 범위로 비교)."""
    if value is None or band is None:
        return False
    if isinstance(band, (list, tuple)):
        return _check_band(value, band)
    return abs(float(value)) >= abs(float(band))


def _check_ma_cross(metrics, prev_metrics):
    """단기 평균선과 장기 평균선이 교차했는지 본다 (골든/데드 크로스)."""
    if not prev_metrics:
        return None
    a, b = metrics.get("ma50"), metrics.get("ma200")
    pa, pb = prev_metrics.get("ma50"), prev_metrics.get("ma200")
    if None in (a, b, pa, pb):
        return None
    cur = float(a) - float(b)
    pre = float(pa) - float(pb)
    if cur == 0 or pre == 0 or (cur > 0) == (pre > 0):
        return None
    label = "Golden Cross (50↑>200)" if cur > 0 else "Death Cross (50↓<200)"
    return ("🟡 caution", f"MA cross: {label}")


def eval_row(r: dict[str, Any]):
    """지표 하나를 보고 가장 센 경고 등급과 그 이유를 돌려준다.

    여러 기준을 모두 확인한 뒤 그중 제일 센 등급을 고른다.
    등급이 없으면(None) 조용히 넘어간다 — 매일 알림은 '강한 신호' 수에서 빼고, 평일 알림은 보내지 않는다.
    """
    metrics = r.get("metrics") or {}
    thresholds = thresholds_for(r)
    curr = r.get("curr")
    prev_value = r.get("prev_value")
    if not thresholds:
        return (None, None)

    best_tier = None
    best_reason = None

    def _consider(tier_lv, reason):
        nonlocal best_tier, best_reason
        if tier_lv is None:
            return
        new = stronger(best_tier, tier_lv)
        if new != best_tier:
            best_tier = new
            best_reason = reason

    # 1) 평소 대비 얼마나 튀었나 (z점수)
    z = metrics.get("z")
    zb = thresholds.get("zscore") or {}
    if z is not None and zb:
        for name in ("alert", "caution", "watch"):
            if _check_band(z, zb.get(name)):
                _consider(_EMOJI[name], f"z={float(z):+.2f}")
                break

    # 1b) 레벨 z — 레벨 자체가 평소 대비 얼마나 높은가 (밸류에이션·비율)
    lz = metrics.get("level_z")
    lzb = thresholds.get("level_z") or {}
    if lz is not None and lzb:
        for name in ("alert", "caution", "watch"):
            if _check_band(lz, lzb.get(name)):
                _consider(_EMOJI[name], f"level_z={float(lz):+.2f}")
                break

    # 1c) 역사적 백분위 — 현재 값이 역사적으로 비싼/싼 구간인가 (밸류에이션)
    pctl = metrics.get("percentile")
    pb = thresholds.get("percentile") or {}
    if pctl is not None and pb:
        for name in ("alert", "caution", "watch"):
            if _check_band(pctl, pb.get(name)):
                _consider(_EMOJI[name], f"pctl={float(pctl):.0f}%")
                break

    # 2) 현재 값 자체가 위험 구간인가
    vb = thresholds.get("value") or {}
    if curr is not None and vb:
        for name in ("alert", "caution", "watch"):
            if _check_band(curr, vb.get(name)):
                _consider(_EMOJI[name], f"value={float(curr):g}")
                break

    # 3) 전날 대비 변화폭
    dcb = thresholds.get("daily_change") or {}
    if curr is not None and prev_value is not None and dcb:
        diff = float(curr) - float(prev_value)
        for name in ("alert", "caution", "watch"):
            if _check_band(diff, dcb.get(name)):
                pct = (diff / abs(float(prev_value)) * 100) if prev_value else diff
                _consider(_EMOJI[name], f"daily_change={pct:+.2f}%")
                break

    # 4) 고점 대비 하락폭 / 저점 대비 반등폭
    for key in ("drawdown", "rebound", "drawdown_bps", "rebound_bps"):
        m = metrics.get(key)
        band = thresholds.get(key) or {}
        if m is None or not band:
            continue
        for name in ("alert", "caution", "watch"):
            if _check_signed(m, band.get(name)):
                unit = " bp" if key.endswith("_bps") else "%"
                _consider(_EMOJI[name], f"{key}={float(m):+.2f}{unit}")
                break

    # 5) 평균선 교차 (가격 지표만 해당)
    mc = _check_ma_cross(metrics, r.get("prev_metrics") or {})
    if mc is not None:
        _consider(mc[0], mc[1])

    return (best_tier, best_reason)
