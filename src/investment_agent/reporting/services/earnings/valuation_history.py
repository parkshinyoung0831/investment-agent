"""역사적 밸류에이션 계산 — 저장(MV) 없이 알림 실행 때 Python으로 산출.

거래일별:  시총 = 종가 × 그날 발행주식수(as-of)
           그날까지 이미 공시된(available_date = filed_at ≤ trade_date) 최신 TTM 실적을 붙여
           PER / PBR / PSR / EV·EBITDA / FCF수익률 계산.
요약:      1·3·5·7년 윈도의 중앙값·25/75분위·현재 백분위.

핵심: 미래 공시를 과거 날짜에 쓰지 않는다(look-ahead 방지) — available_date as-of 조인.
yfinance 종가(close)를 쓰되, 이 값은 과거 분할이 반영되어 있으므로 발행주식수도
split_ratio로 현재 분할 기준에 맞춘다. adj_close는 배당까지 반영하므로 사용하지 않는다.
"""
from __future__ import annotations

import bisect
import statistics
from datetime import date, timedelta
from typing import Any

METRICS = ("pe", "pb", "ps", "ev_ebitda", "fcf_yield")
_WINDOWS = (1, 3, 5, 7)
_MIN_POINTS = 20  # 윈도당 최소 관측치(주 단위로도 충분)


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _asof(sorted_dates: list[str], target: str) -> int:
    """sorted_dates(오름차순)에서 target 이하 최신 인덱스, 없으면 -1."""
    return bisect.bisect_right(sorted_dates, target) - 1


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _positive_den_ratio(num: float | None, den: float | None) -> float | None:
    """PER·PBR처럼 분모가 양수일 때만 의미가 있는 배수."""
    if num is None or den is None or den <= 0:
        return None
    return num / den


def split_adjust_shares(
    shares: list[tuple[str, float]],
    splits: list[tuple[str, float]],
) -> list[tuple[str, float]]:
    """분할조정 종가와 맞도록 과거 발행주식수를 현재 분할 기준으로 환산한다."""
    valid_splits = [(d, r) for d, r in splits if r and r > 0]
    out = []
    for as_of, count in shares:
        factor = 1.0
        for split_date, ratio in valid_splits:
            # yfinance shares 이력은 분할일 스냅샷도 분할 전 수량인 경우가 있다.
            if split_date >= as_of:
                factor *= ratio
        out.append((as_of, count * factor))
    return out


def daily_series(
    prices: list[tuple[str, float]],
    shares: list[tuple[str, float]],
    snaps: list[dict],
    splits: list[tuple[str, float]] | None = None,
) -> tuple[list[str], dict[str, list[float | None]]]:
    """거래일별 밸류에이션 시계열. prices/shares/snaps 모두 날짜 오름차순 전제."""
    shares = split_adjust_shares(shares, splits or [])
    sh_dates = [s[0] for s in shares]
    snap_dates = [s["available_date"] for s in snaps]
    dates: list[str] = []
    series: dict[str, list[float | None]] = {k: [] for k in METRICS}

    for td, close in prices:
        si = _asof(sh_dates, td)
        fi = _asof(snap_dates, td)
        if si < 0 or fi < 0 or close is None:
            continue
        mcap = close * shares[si][1]
        snap = snaps[fi]
        ev = mcap + (_f(snap.get("ev_ex_market_cap")) or 0.0)
        dates.append(td)
        series["pe"].append(_positive_den_ratio(mcap, _f(snap.get("earnings_ttm"))))
        series["pb"].append(_positive_den_ratio(mcap, _f(snap.get("book_value"))))
        series["ps"].append(_positive_den_ratio(mcap, _f(snap.get("revenue_ttm"))))
        series["ev_ebitda"].append(_positive_den_ratio(ev, _f(snap.get("ebitda_ttm"))))
        series["fcf_yield"].append(_ratio(_f(snap.get("fcf_ttm")), mcap))
    return dates, series


def window_stats(dates: list[str], vals: list[float | None], today: date) -> dict[int, dict] | None:
    """지표 한 개의 1/3/5/7년 윈도 통계(현재값·중앙값·분위·백분위·관측수·기간)."""
    if not vals or vals[-1] is None:
        return None
    paired = [(d, v) for d, v in zip(dates, vals) if v is not None]
    if not paired:
        return None
    current = vals[-1]
    out: dict[int, dict] = {}
    for years in _WINDOWS:
        cutoff = (today - timedelta(days=int(years * 365.25))).isoformat()
        xs = [v for d, v in paired if d >= cutoff]
        if len(xs) < _MIN_POINTS:
            continue
        xs_sorted = sorted(xs)
        m = len(xs_sorted)
        pct = sum(1 for v in xs_sorted if v <= current) / m * 100

        def _q(p: float) -> float:
            return xs_sorted[min(m - 1, max(0, int(p * m)))]

        out[years] = {
            "current": current,
            "mean": statistics.fmean(xs),
            "median": statistics.median(xs),
            "q25": _q(0.25),
            "q75": _q(0.75),
            "lo": _q(0.05),   # 5/95분위 = 트랙 축 경계(극단치로 분포가 짓눌리지 않게)
            "hi": _q(0.95),
            "percentile": round(pct),
            "n": m,
        }
    return out or None


def downsample_weekly(dates: list[str], vals: list[float | None]) -> list[tuple[str, float]]:
    """스파크라인용 주 단위 다운샘플(각 주의 마지막 유효값)."""
    out: list[tuple[str, float]] = []
    seen: set[str] = set()
    for d, v in zip(reversed(dates), reversed(vals)):
        if v is None:
            continue
        wk = d[:4] + d[5:7] + str(int(d[8:10]) // 7)  # 연-월-주차 버킷
        if wk in seen:
            continue
        seen.add(wk)
        out.append((d, v))
    return list(reversed(out))


def compute(
    prices: list[tuple[str, float]],
    shares: list[tuple[str, float]],
    snaps: list[dict],
    *,
    splits: list[tuple[str, float]] | None = None,
    today: date | None = None,
) -> dict | None:
    """한 종목의 역사 밸류에이션 전체: 지표별 윈도 통계 + PER 스파크라인."""
    if not prices or not shares or not snaps:
        return None
    today = today or date.today()
    dates, series = daily_series(prices, shares, snaps, splits)
    if not dates:
        return None
    stats = {m: window_stats(dates, series[m], today) for m in METRICS}
    return {
        "stats": {m: s for m, s in stats.items() if s},
        "pe_spark": downsample_weekly(dates, series["pe"]),
        "span_days": (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days,
    }
