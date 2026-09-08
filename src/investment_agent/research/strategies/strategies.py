"""투자 전략 6종 계산 핵심 파일.
월별 종가 → 전략별 자산 비중. compute_all() 하나로 6개 전략 일괄 계산."""
from __future__ import annotations

import pandas as pd

from investment_agent.platform.logging import get_logger
from investment_agent.research.strategies import (
    GTAA5_ASSETS,
    HAA_BAL_OFFENSIVE,
    HAA_CANARY,
    HAA_SIM_OFFENSIVE,
    SMA_MONTHS,
    SPDR_SECTORS,
)
from investment_agent.research.strategies.catalog import ensure_registered_strategies

log = get_logger(__name__)


# ── 점수 계산용 보조 함수들 ───────────────────
def _complete_tail(rets: pd.DataFrame, ticker: str, n: int) -> pd.Series | None:
    """최신 월을 포함한 연속 n개월 수익률만 반환한다."""
    if ticker not in rets.columns or len(rets) < n:
        return None
    series = rets[ticker].iloc[-n:]
    if series.isna().any():
        return None
    periods = pd.DatetimeIndex(series.index).to_period("M")
    expected = pd.period_range(periods[0], periods[-1], freq="M")
    if len(expected) != n or not periods.equals(expected):
        return None
    return series


def cum_ret(rets: pd.DataFrame, ticker: str, n: int) -> float | None:
    """최근 n개월 동안의 누적 수익률. 데이터가 모자라면 None."""
    series = _complete_tail(rets, ticker, n)
    return None if series is None else float((1 + series).prod() - 1)


def score_13612w(rets: pd.DataFrame, t: str) -> float | None:
    """최근 1·3·6·12개월 수익률의 동일가중 평균 모멘텀 (HAA 13612)."""
    rs = [cum_ret(rets, t, n) for n in (1, 3, 6, 12)]
    return None if any(v is None for v in rs) else (rs[0] + rs[1] + rs[2] + rs[3]) / 4


def score_adm(rets: pd.DataFrame, t: str) -> float | None:
    """최근 1·3·6개월 수익률의 평균으로 낸 모멘텀 점수 (ADM 방식)."""
    rs = [cum_ret(rets, t, n) for n in (1, 3, 6)]
    return None if any(v is None for v in rs) else sum(rs) / 3


def index_series(rets: pd.DataFrame, t: str) -> pd.Series | None:
    """수익률을 누적해 '가격 흐름' 곡선으로 바꾼다 (평균선 계산에 사용)."""
    series = _complete_tail(rets, t, SMA_MONTHS)
    return None if series is None else (1 + series).cumprod()


def defensive(rets: pd.DataFrame) -> str | None:
    """안전자산 두 개(BIL·IEF) 중 점수가 더 높은 쪽을 고른다."""
    b = score_13612w(rets, "BIL")
    i = score_13612w(rets, "IEF")
    if b is None or i is None:
        return None
    return "BIL" if b >= i else "IEF"


def _wrap(strategy_id: str, mode: str, alloc: dict, signals: dict | None = None) -> dict:
    """계산 결과를 저장하기 좋은 형태로 정리 (비중은 소수점 6자리로 반올림)."""
    return {
        "strategy_id": strategy_id,
        "mode": mode,
        "weights": {k: round(float(v), 6) for k, v in alloc.items()},
        "signals": signals or {},
    }


# ── 6개 전략 계산 함수 ───────────────────────
def _gem(rets: pd.DataFrame) -> dict | None:
    """GEM 전략: 미국주식(SPY)·해외주식(EFA)·현금(BIL)의 12개월 성과를 비교해
    위험자산 승자가 현금보다 강하면 그 승자에 투자하고, 아니면 안전자산으로 피한다."""
    spy = cum_ret(rets, "SPY", 12)
    efa = cum_ret(rets, "EFA", 12)
    bil = cum_ret(rets, "BIL", 12)
    if any(v is None for v in (spy, efa, bil)):
        return None
    winner = ("SPY", spy) if spy >= efa else ("EFA", efa)
    if winner[1] < bil:
        alloc, mode = {"AGG": 1.0}, "Risk-Off"
    elif winner[0] == "SPY":
        alloc, mode = {"SPY": 1.0}, "Risk-On-US"
    else:
        alloc, mode = {"EFA": 1.0}, "Risk-On-INTL"
    return _wrap("gem", mode, alloc,
                 {"spy_12m": round(spy, 4), "efa_12m": round(efa, 4),
                  "bil_12m": round(bil, 4)})


def _adm(rets: pd.DataFrame) -> dict | None:
    """ADM 전략: 미국주식(SPY)과 해외소형주(SCZ) 중 점수가 높은 쪽에 100% 투자.
    단, 승자 점수도 0 이하로 나쁘면 장기국채(TLT)로 피한다."""
    spy = score_adm(rets, "SPY")
    scz = score_adm(rets, "SCZ")
    if spy is None or scz is None:
        return None
    winner = ("SPY", spy) if spy >= scz else ("SCZ", scz)
    if winner[1] <= 0:
        alloc, mode = {"TLT": 1.0}, "Risk-Off (TLT)"
    else:
        alloc = {winner[0]: 1.0}
        mode = "Risk-On-US" if winner[0] == "SPY" else "Risk-On-INTL"
    return _wrap("adm", mode, alloc,
                 {"spy_score": round(spy, 4), "scz_score": round(scz, 4)})


def _dmsr(rets: pd.DataFrame) -> dict | None:
    """DMSR 전략: 미국 11개 업종 중 12개월 성과 상위 4개를 고른다.
    그중 현금보다 나은 업종에만 25%씩 담고, 남는 비중은 채권(AGG)에 둔다."""
    bil = cum_ret(rets, "BIL", 12)
    if bil is None:
        return None
    scored = [(s, m) for s in SPDR_SECTORS if (m := cum_ret(rets, s, 12)) is not None]
    if len(scored) != len(SPDR_SECTORS):
        return None
    top4 = sorted(scored, key=lambda x: -x[1])[:4]
    alloc = {s: 0.25 for s, m in top4 if m > bil}
    passed = len(alloc)
    if passed < 4:
        alloc["AGG"] = 1 - passed * 0.25
    return _wrap("dmsr", f"Top-4 통과 {passed}/4", alloc,
                 {"top4": [{"ticker": s, "mom12": round(m, 4)} for s, m in top4],
                  "bil_12m": round(bil, 4)})


def _gtaa5(rets: pd.DataFrame) -> dict | None:
    """GTAA-5 전략: 5개 자산 각각이 '최근 10개월 평균선' 위에 있으면 20%씩 편입.
    조건을 못 채운 만큼은 현금(BIL)에 둔다."""
    alloc: dict = {}
    signals: dict = {}
    for a in GTAA5_ASSETS:
        idx = index_series(rets, a)
        if idx is None or len(idx) < SMA_MONTHS:
            return None
        sma10 = float(idx.iloc[-SMA_MONTHS:].mean())
        last_px = float(idx.iloc[-1])
        in_market = last_px > sma10
        signals[a] = {"inMarket": in_market,
                      "last": round(last_px, 4),
                      "sma10": round(sma10, 4)}
        if in_market:
            alloc[a] = 0.20
    included = len(alloc)
    if included < 5:
        alloc["BIL"] = 1 - included * 0.20
    return _wrap("gtaa5", f"편입 {included}/5", alloc, signals)


def _haa_balanced(rets: pd.DataFrame) -> dict | None:
    """HAA-Balanced 전략: 'TIP'을 위험 신호등으로 본다.
    안전하면 8개 자산 중 상위 4개에 25%씩(점수가 나쁜 것은 안전자산으로 교체),
    위험하면 안전자산(BIL/IEF)에 100% 담는다."""
    tip = score_13612w(rets, HAA_CANARY[0])
    if tip is None:
        return None
    if tip <= 0:
        defensive_asset = defensive(rets)
        if defensive_asset is None:
            return None
        return _wrap("haa_bal", "Defensive (Canary OFF)",
                     {defensive_asset: 1.0}, {"tip_13612w": round(tip, 4)})
    scored = [(a, s) for a in HAA_BAL_OFFENSIVE if (s := score_13612w(rets, a)) is not None]
    if len(scored) != len(HAA_BAL_OFFENSIVE):
        return None
    top4 = sorted(scored, key=lambda x: -x[1])[:4]
    d = defensive(rets)
    if d is None:
        return None
    alloc: dict = {}
    for a, s in top4:
        key = a if s > 0 else d
        alloc[key] = alloc.get(key, 0) + 0.25
    return _wrap("haa_bal", "Attack (Canary ON)", alloc,
                 {"tip_13612w": round(tip, 4),
                  "top4": [{"ticker": a, "score": round(s, 4)} for a, s in top4]})


def _haa_simple(rets: pd.DataFrame) -> dict | None:
    """HAA-Simple 전략: 'TIP'을 위험 신호등으로 본다.
    안전하면 4개 자산 중 가장 좋은 1개에 100%, 위험하면 안전자산(BIL/IEF)에 100%."""
    tip = score_13612w(rets, HAA_CANARY[0])
    if tip is None:
        return None
    if tip <= 0:
        defensive_asset = defensive(rets)
        if defensive_asset is None:
            return None
        return _wrap("haa_sim", "Defensive (Canary OFF)",
                     {defensive_asset: 1.0}, {"tip_13612w": round(tip, 4)})
    scored = [(a, s) for a in HAA_SIM_OFFENSIVE if (s := score_13612w(rets, a)) is not None]
    if len(scored) != len(HAA_SIM_OFFENSIVE):
        return None
    name, score = max(scored, key=lambda x: x[1])
    if score > 0:
        alloc, mode = {name: 1.0}, "Attack"
    else:
        defensive_asset = defensive(rets)
        if defensive_asset is None:
            return None
        alloc, mode = {defensive_asset: 1.0}, "Defensive (neg score)"
    return _wrap("haa_sim", mode, alloc,
                 {"tip_13612w": round(tip, 4),
                  "top1": {"ticker": name, "score": round(score, 4)}})


# ── 직렬 실행기 ────────────────────────────────────
# 실행할 전략 6개 (순서대로 실행)
_STRATEGIES = [
    ("gem",     _gem),
    ("adm",     _adm),
    ("dmsr",    _dmsr),
    ("gtaa5",   _gtaa5),
    ("haa_bal", _haa_balanced),
    ("haa_sim", _haa_simple),
]
ensure_registered_strategies({sid for sid, _ in _STRATEGIES})

# 룰 하나만 따로 돌려야 하는 읽기 전용 소비자(대시보드 룰 재현 백테스트)를 위한 공개 registry.
# 여기를 통해 부르면 월간 적재와 화면 재현이 같은 함수를 쓴다 — 규칙이 갈라지지 않는다.
STRATEGY_IDS: tuple[str, ...] = tuple(sid for sid, _ in _STRATEGIES)


def monthly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """월별 종가 표를 전략 계산이 받는 월간 수익률 표로 바꾼다."""
    return prices.pct_change(fill_method=None).dropna(how="all")


def compute_one(strategy_id: str, rets: pd.DataFrame) -> dict | None:
    """전략 하나를 계산한다. 데이터가 모자라면 None (예외를 만들지 않는다)."""
    for sid, fn in _STRATEGIES:
        if sid == strategy_id:
            return fn(rets)
    raise KeyError(f"unknown strategy_id: {strategy_id}")


def compute_all(prices: pd.DataFrame) -> list[dict]:
    """6개 전략을 모두 계산한다. 하나라도 불완전하면 전체 실행을 실패시킨다."""
    rets = monthly_returns(prices)
    out: list[dict] = []
    failures: list[str] = []
    for sid, _fn in _STRATEGIES:
        try:
            res = compute_one(sid, rets)
        except Exception as e:
            log.exception("strategy %s failed", sid)
            failures.append(f"{sid}: {type(e).__name__}: {e}")
            continue
        if res is None:
            failures.append(f"{sid}: data-insufficient-or-stale")
            continue
        out.append(res)
    if failures:
        raise RuntimeError("strategy calculation incomplete: " + "; ".join(failures))
    return out
