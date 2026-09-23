"""System 목표 한 건이 H거래일 뒤 SPY 대비 번 것·잃은 것을 단계별로 나눈다 — 어느 단계가 틀렸나.

목표를 만들 때 종목마다 단계별 값(factor 사전값 → ML → 논지 → 최종 기대수익 → 비중)을 `stage_trace`로
남긴다. H거래일 뒤 실현 수익이 나오면 그 목표의 SPY 대비 성과를 정확히 넷으로 나눈다. 목표 비중을 H일
그대로 들고 있었다고 보는 분해라, 중간 재조정·비중 표류는 들어가지 않는다(NAV와 다를 수 있다).

```
active = Σ w_i·(r_i − r_b) − cash·r_b
       = W·ē_U                후보군 효과 — Universe·Factor가 모은 후보 전체가 SPY를 이겼나
       + W·(ē_H − ē_U)        선택 효과   — Alpha가 후보 중 담은 종목이 후보 평균을 이겼나
       + Σ w_i·(e_i − ē_H)    비중 효과   — Optimizer가 더 많이 담은 종목이 더 벌었나
       − cash·r_b             노출 효과   — 현금으로 둔 몫이 SPY 대비 얼마였나(시장 위험 예산·optimizer 현금)
```

`e_i = r_i − r_b`, `W = Σ w_i`(위험자산), `ē_U`는 신호를 받은 후보 전체의 평균, `ē_H`는 실제로 담은 종목의
단순 평균이다. 네 항의 합은 항등식이라 잔차가 없다.

돈의 분해와 별도로 **정보의 분해**를 한다. 각 단계의 값이 실현 초과수익의 순위를 맞혔는가(rank IC)와,
각 차단 규칙(품질 탈락·검증 전 편입 차단·논지 거부권·중복 차단)에 걸린 종목이 실제로 후보 평균보다 못했는가.
차단된 종목이 오히려 더 벌었다면 그 규칙이 기회를 버린 것이다.

판정은 겹치지 않는 목표만으로 한다. 주간 목표를 60일로 채점하면 이웃한 12개가 같은 60일을 공유해 표본이
부풀려진다.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from investment_agent.portfolio_weights import CASH_SYMBOL

STAGE_TRACE_VERSION = "stage-trace-v1"
DIAGNOSIS_VERSION = "stage-diagnosis-v1"
# 5일은 체결·단기 반응, 20일은 신호 기간(SIGNAL_HORIZON_DAYS), 60·120일은 factor가 원래 노리는 중기다.
DIAGNOSIS_HORIZONS = (5, 20, 60, 120)
# 순위 상관은 이보다 적은 종목으로는 계산하지 않는다.
_MIN_RANK_NAMES = 8
# 판정은 겹치지 않는 목표가 이만큼은 있어야 한다.
_MIN_VERDICT_SAMPLES = 8
_T_THRESHOLD = 2.0

COMPONENTS = ("universe_effect", "selection_effect", "sizing_effect", "exposure_effect")
# 차단 규칙과 그 규칙이 옳았을 때의 부호. 차단한 종목은 후보 평균보다 못해야 한다(−).
GATE_REASONS = ("FACTOR_BREAKDOWN", "UNVERIFIED_ENTRY_BLOCKED", "THESIS_VETO", "THESIS_BROKEN", "REDUNDANT_BLOCKED")


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def stage_trace(
    *,
    alpha_detail: Mapping[str, Mapping[str, Any]],
    alpha_reasons: Mapping[str, str],
    current_weights: Mapping[str, float],
    proposed_weights: Mapping[str, float],
    approved_weights: Mapping[str, float] | None,
    is_approved: bool,
    market_regime: str | None,
    min_cash_weight: float,
    redundant_blocked: Sequence[str] = (),
) -> dict[str, Any]:
    """목표 하나를 만든 단계별 값. 나중에 실현 수익과 맞대어 어느 단계가 틀렸는지 가른다."""
    approved = dict(approved_weights or {})
    symbols = (set(alpha_detail) | set(alpha_reasons) | set(current_weights) | set(proposed_weights)
               | set(approved)) - {CASH_SYMBOL}
    securities: dict[str, dict[str, Any]] = {}
    for symbol in sorted(symbols):
        detail = alpha_detail.get(symbol) or {}
        securities[symbol] = {
            "prior": _round(detail.get("factor_prior")),
            "ml": _round(detail.get("ml_expected_excess_return")),
            "ml_share": _round(detail.get("ml_share")),
            "alpha": _round(detail.get("expected_excess_return")),
            "confidence": _round(detail.get("confidence"), 4),
            "thesis": detail.get("thesis_state"),
            "reason": "REDUNDANT_BLOCKED" if symbol in redundant_blocked else alpha_reasons.get(symbol),
            "before": _round(current_weights.get(symbol, 0.0)),
            "proposed": _round(proposed_weights.get(symbol, 0.0)),
            "approved": _round(approved.get(symbol, 0.0)) if is_approved else None,
        }
    return {
        "version": STAGE_TRACE_VERSION,
        "market_regime": market_regime,
        "min_cash_weight": _round(min_cash_weight),
        "is_approved": bool(is_approved),
        "cash": {
            "before": _round(current_weights.get(CASH_SYMBOL, 0.0)),
            "proposed": _round(proposed_weights.get(CASH_SYMBOL, 0.0)),
            "approved": _round(approved.get(CASH_SYMBOL, 0.0)) if is_approved else None,
        },
        "securities": securities,
    }


class PricePaths:
    """종목별 가격 경로를 한 번만 읽어 H거래일 총수익(배당 포함)을 낸다.

    `market.prices_daily.close`는 분할 조정 가격이라 같은 조회 안에서는 분할 비율을 곱하지 않는다.
    """

    def __init__(self, fetch: Callable[[str], Sequence[Mapping[str, Any]]]):
        self._fetch = fetch
        self._paths: dict[str, tuple[list[str], list[float], list[float]]] = {}

    def _path(self, symbol: str) -> tuple[list[str], list[float], list[float]]:
        if symbol not in self._paths:
            dates: list[str] = []
            closes: list[float] = []
            dividends: list[float] = []
            for row in sorted(self._fetch(symbol), key=lambda item: str(item["trade_date"])[:10]):
                close = row.get("close")
                if close is None or float(close) <= 0:
                    continue
                dates.append(str(row["trade_date"])[:10])
                closes.append(float(close))
                dividends.append(float(row.get("div_amount") or 0.0))
            self._paths[symbol] = (dates, closes, dividends)
        return self._paths[symbol]

    def forward_return(self, symbol: str, *, after: str, horizon: int) -> tuple[float, str, str] | None:
        """`after` 날짜의 종가(없으면 그 이전 마지막 종가)에서 H거래일 뒤까지의 총수익과 시작·끝 날짜."""
        dates, closes, dividends = self._path(symbol)
        start = bisect_right(dates, after) - 1
        end = start + horizon
        if start < 0 or end >= len(dates):
            return None
        total = (closes[end] + math.fsum(dividends[start + 1:end + 1])) / closes[start] - 1.0
        return total, dates[start], dates[end]


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        tie_end = position
        while tie_end + 1 < len(order) and values[order[tie_end + 1]] == values[order[position]]:
            tie_end += 1
        average = (position + tie_end) / 2.0
        for index in order[position:tie_end + 1]:
            ranks[index] = average
        position = tie_end + 1
    return ranks


def rank_ic(pairs: Sequence[tuple[float, float]]) -> float | None:
    """순위 상관(Spearman). 한쪽 값이 모두 같으면 정의되지 않아 None이다."""
    if len(pairs) < _MIN_RANK_NAMES:
        return None
    left, right = _ranks([item[0] for item in pairs]), _ranks([item[1] for item in pairs])
    mean_left, mean_right = sum(left) / len(left), sum(right) / len(right)
    covariance = math.fsum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    spread = math.sqrt(math.fsum((a - mean_left) ** 2 for a in left) * math.fsum((b - mean_right) ** 2 for b in right))
    return covariance / spread if spread > 0 else None


def _pre_thesis(row: Mapping[str, Any]) -> float | None:
    prior = row.get("prior")
    if prior is None:
        return None
    ml, share = row.get("ml"), float(row.get("ml_share") or 0.0)
    return float(prior) if ml is None else (1.0 - share) * float(prior) + share * float(ml)


def diagnose_target(
    trace: Mapping[str, Any],
    prices: PricePaths,
    *,
    decided_on: str,
    horizon: int,
    benchmark: str = "SPY",
) -> dict[str, Any] | None:
    """목표 하나의 H거래일 단계 분해. 벤치마크 경로가 H일을 못 채우면 아직 채점할 수 없어 None이다."""
    bench = prices.forward_return(benchmark, after=decided_on, horizon=horizon)
    if bench is None:
        return None
    benchmark_return, start_date, end_date = bench
    excess: dict[str, float] = {}
    for symbol in trace.get("securities") or {}:
        path = prices.forward_return(symbol, after=decided_on, horizon=horizon)
        # 시작·끝 날짜가 벤치마크와 다르면(거래 정지·상장 폐지) 같은 기간이 아니라 채점하지 않는다.
        if path is not None and path[1] == start_date and path[2] == end_date:
            excess[symbol] = path[0] - benchmark_return
    securities = trace.get("securities") or {}
    candidates = [symbol for symbol in excess if securities[symbol].get("alpha") is not None]
    universe_mean = sum(excess[symbol] for symbol in candidates) / len(candidates) if candidates else None

    def ic(field: Callable[[Mapping[str, Any]], float | None]) -> float | None:
        pairs = [(value, excess[symbol]) for symbol in candidates
                 if (value := field(securities[symbol])) is not None]
        return rank_ic(pairs)

    alpha_ic = ic(lambda row: row.get("alpha"))
    pre_thesis_ic = ic(_pre_thesis)
    information = {
        "factor_ic": ic(lambda row: row.get("prior")),
        "ml_ic": ic(lambda row: row.get("ml")),
        "alpha_ic": alpha_ic,
        # 논지가 순위 정보를 더했나(+) 망쳤나(−). 논지가 하나도 없으면 두 값이 같아 0이다.
        "thesis_ic_delta": alpha_ic - pre_thesis_ic if alpha_ic is not None and pre_thesis_ic is not None else None,
    }
    gates: dict[str, dict[str, Any]] = {}
    for reason in GATE_REASONS:
        hit = [excess[symbol] for symbol, row in securities.items() if row.get("reason") == reason and symbol in excess]
        if hit and universe_mean is not None:
            gates[reason] = {"count": len(hit), "relative_excess": sum(hit) / len(hit) - universe_mean}
    result: dict[str, Any] = {
        "horizon": horizon, "start_date": start_date, "end_date": end_date,
        "benchmark_return": benchmark_return, "scored_names": len(excess),
        "candidate_mean_excess": universe_mean, "information": information, "gates": gates,
        "is_approved": bool(trace.get("is_approved")),
    }
    weights = {symbol: float(row.get("approved") or 0.0) for symbol, row in securities.items()}
    if not trace.get("is_approved") or universe_mean is None:
        return result
    held = {symbol: weight for symbol, weight in weights.items() if weight > 0}
    missing = sum(weight for symbol, weight in held.items() if symbol not in excess)
    held = {symbol: weight for symbol, weight in held.items() if symbol in excess}
    cash = float((trace.get("cash") or {}).get("approved") or 0.0)
    invested = sum(held.values())
    held_mean = sum(excess[symbol] for symbol in held) / len(held) if held else 0.0
    components = {
        "universe_effect": invested * universe_mean,
        "selection_effect": invested * (held_mean - universe_mean),
        "sizing_effect": math.fsum(weight * (excess[symbol] - held_mean) for symbol, weight in held.items()),
        "exposure_effect": -cash * benchmark_return,
    }
    result.update({
        "components": components,
        "active_return": math.fsum(components.values()),
        "cash_weight": cash,
        # 채점하지 못한 보유 비중. 크면 분해가 포트폴리오 전체를 대표하지 못한다.
        "unscored_weight": missing,
    })
    return result


def _verdict(values: Sequence[float], *, good_sign: int = 1) -> dict[str, Any]:
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "t": None, "verdict": "no_data"}
    mean = math.fsum(values) / n
    if n < 2:
        return {"n": n, "mean": mean, "t": None, "verdict": "insufficient"}
    sd = math.sqrt(math.fsum((value - mean) ** 2 for value in values) / (n - 1))
    # 값이 모두 같으면(부동소수점 잡음만 남으면) t가 무한대로 튄다 — 정의하지 않는다.
    t = mean / (sd / math.sqrt(n)) if sd > 1e-12 else None
    if n < _MIN_VERDICT_SAMPLES or t is None:
        verdict = "insufficient"
    elif good_sign * t >= _T_THRESHOLD:
        verdict = "helped"
    elif good_sign * t <= -_T_THRESHOLD:
        verdict = "hurt"
    else:
        verdict = "inconclusive"
    return {"n": n, "mean": mean, "t": t, "verdict": verdict}


def non_overlapping(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """앞 목표의 채점 구간이 끝난 뒤 시작하는 목표만 남긴다(시작일 순)."""
    kept: list[Mapping[str, Any]] = []
    last_end = ""
    for row in sorted(rows, key=lambda item: item["start_date"]):
        if row["start_date"] >= last_end:
            kept.append(row)
            last_end = row["end_date"]
    return kept


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """한 기간(horizon)의 목표별 분해를 모아 단계마다 도움·손해·판정 불가를 낸다.

    평균은 모든 목표로, 판정(t)은 겹치지 않는 목표로 한다.
    """
    independent = non_overlapping(rows)
    portfolio = [row for row in rows if "components" in row]
    portfolio_independent = [row for row in independent if "components" in row]
    components = {}
    for name in COMPONENTS:
        verdict = _verdict([row["components"][name] for row in portfolio_independent])
        verdict["mean_all_targets"] = (math.fsum(row["components"][name] for row in portfolio) / len(portfolio)
                                       if portfolio else None)
        components[name] = verdict
    information = {
        name: _verdict([row["information"][name] for row in independent if row["information"].get(name) is not None])
        for name in ("factor_ic", "ml_ic", "alpha_ic", "thesis_ic_delta")
    }
    gates = {
        reason: {**_verdict([row["gates"][reason]["relative_excess"] for row in independent if reason in row["gates"]],
                            good_sign=-1),
                 "names_blocked": sum(row["gates"][reason]["count"] for row in rows if reason in row["gates"])}
        for reason in GATE_REASONS
    }
    judged = [(name, item["mean"]) for name, item in components.items() if item["mean"] is not None]
    worst = min(judged, key=lambda item: item[1]) if judged else None
    return {
        "targets": len(rows),
        "independent_targets": len(independent),
        "rejected_targets": sum(not row.get("is_approved") for row in rows),
        "active_return": _verdict([row["active_return"] for row in portfolio_independent]),
        "components": components,
        "information": information,
        "gates": gates,
        # 평균적으로 SPY 대비 가장 많이 깎은 단계. 판정(t)과 함께 읽는다.
        "largest_drag": {"component": worst[0], "mean": worst[1]} if worst and worst[1] < 0 else None,
    }


def diagnose(
    targets: Sequence[tuple[str, Mapping[str, Any]]],
    prices: PricePaths,
    *,
    horizons: Sequence[int] = DIAGNOSIS_HORIZONS,
    benchmark: str = "SPY",
) -> dict[str, Any]:
    """(결정일, stage_trace) 목록을 기간마다 채점해 요약한다. trace가 없는 옛 목표는 건너뛴다."""
    traced = [(day, trace) for day, trace in targets if isinstance(trace, Mapping) and trace.get("securities")]
    by_horizon: dict[str, Any] = {}
    for horizon in horizons:
        rows = [row for day, trace in traced
                if (row := diagnose_target(trace, prices, decided_on=day, horizon=horizon, benchmark=benchmark))]
        by_horizon[str(horizon)] = summarize(rows)
    return {"version": DIAGNOSIS_VERSION, "traced_targets": len(traced), "untraced_targets": len(targets) - len(traced),
            "horizons": by_horizon}


__all__ = [
    "COMPONENTS",
    "DIAGNOSIS_HORIZONS",
    "DIAGNOSIS_VERSION",
    "GATE_REASONS",
    "PricePaths",
    "STAGE_TRACE_VERSION",
    "diagnose",
    "diagnose_target",
    "non_overlapping",
    "rank_ic",
    "stage_trace",
    "summarize",
]
