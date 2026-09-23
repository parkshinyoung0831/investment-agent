"""TradingAgents 판단 성적표 — 논지가 맞았나, 확률이 보정됐나, 기대수익의 순위가 맞았나.

판단 하나하나의 5·20·60거래일 결과(`decision_evaluations`)는 다음 판단의 기억(CaseMemory)으로만 쓰였다.
모아서 보지 않으면 "LLM 논지가 돈을 벌게 했나"를 누구도 묻지 않는다. 기간·엔진 버전별로 셋을 본다.

- **논지 적중**: 긍정 논지의 실현 초과수익 평균과 부정 논지의 평균, 그 차이(spread). 차이가 +여야 논지가
  방향 정보를 가진 것이다.
- **확률 보정**: `probability_up`의 Brier 점수를 "항상 실현 비율로 답하는" 기준과 비교한 skill. 구간별로
  말한 확률과 실제로 이긴 비율을 나란히 둔다.
- **순위 정보**: 같은 날 판단들의 `expected_excess_return` 순위와 실현 초과수익 순위의 상관(날짜별 IC 평균).

같은 날의 판단들은 같은 시장을 겪어 독립이 아니다. t는 판단 단위가 아니라 **날짜 단위**로 묶어 계산한다.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from investment_agent.trading.performance.stage_diagnosis import rank_ic

SCORECARD_VERSION = "decision-scorecard-v1"
_CALIBRATION_EDGES = (0.0, 0.4, 0.5, 0.6, 1.0000001)
_MIN_VERDICT_DAYS = 8
_T_THRESHOLD = 2.0


def _mean(values: list[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def _clustered(values_by_day: Mapping[str, list[float]], *, good_sign: int = 1) -> dict[str, Any]:
    """날짜별 평균을 표본으로 한 평균·t·판정."""
    daily = [math.fsum(values) / len(values) for values in values_by_day.values() if values]
    n = len(daily)
    mean = _mean(daily)
    t = None
    if n >= 2:
        sd = math.sqrt(math.fsum((value - mean) ** 2 for value in daily) / (n - 1))
        t = mean / (sd / math.sqrt(n)) if sd > 1e-12 else None
    if n < _MIN_VERDICT_DAYS or t is None:
        verdict = "insufficient"
    elif good_sign * t >= _T_THRESHOLD:
        verdict = "helped"
    elif good_sign * t <= -_T_THRESHOLD:
        verdict = "hurt"
    else:
        verdict = "inconclusive"
    return {"days": n, "decisions": sum(len(values) for values in values_by_day.values()), "mean": mean, "t": t,
            "verdict": verdict}


def _score(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_thesis: dict[str, dict[str, list[float]]] = {}
    spread_days: dict[str, list[float]] = {}
    per_day: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        day = row["day"]
        by_thesis.setdefault(row["thesis"], {}).setdefault(day, []).append(row["excess"])
        per_day.setdefault(day, {}).setdefault(row["thesis"], []).append(row["excess"])
    for day, groups in per_day.items():
        if groups.get("positive") and groups.get("negative"):
            spread_days[day] = [_mean(groups["positive"]) - _mean(groups["negative"])]
    brier = [float(row["brier"]) for row in rows if row.get("brier") is not None]
    outcomes = [1.0 if row["excess"] > 0 else 0.0 for row in rows]
    base_rate = _mean(outcomes)
    reference = base_rate * (1.0 - base_rate) if base_rate is not None else None
    calibration = []
    for low, high in zip(_CALIBRATION_EDGES, _CALIBRATION_EDGES[1:]):
        bucket = [row for row in rows if row.get("probability_up") is not None and low <= row["probability_up"] < high]
        if bucket:
            calibration.append({
                "range": [low, min(high, 1.0)], "decisions": len(bucket),
                "said": _mean([float(row["probability_up"]) for row in bucket]),
                "happened": _mean([1.0 if row["excess"] > 0 else 0.0 for row in bucket]),
            })
    ic_days: dict[str, list[float]] = {}
    for day, day_rows in _group(rows, "day").items():
        value = rank_ic([(row["expected"], row["excess"]) for row in day_rows if row.get("expected") is not None])
        if value is not None:
            ic_days[day] = [value]
    return {
        "decisions": len(rows),
        "thesis": {thesis: _clustered(days) for thesis, days in sorted(by_thesis.items())},
        # 긍정 논지가 부정 논지보다 더 벌었나. 같은 날 둘 다 있을 때만 센다.
        "thesis_spread": _clustered(spread_days),
        "brier": _mean(brier),
        # 1이면 완벽, 0이면 "늘 실현 비율로 답하기"와 같고, 음수면 그보다 못하다.
        "brier_skill": (1.0 - _mean(brier) / reference) if brier and reference else None,
        "base_rate_up": base_rate,
        "calibration": calibration,
        "expected_return_ic": _clustered(ic_days),
    }


def _group(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row[key]), []).append(row)
    return grouped


def decision_scorecard(
    cases: Iterable[Mapping[str, Any]], evaluations: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """판단(`security_decisions`)과 채점(`decision_evaluations`)을 기간·엔진 버전별 성적표로 묶는다."""
    by_case = {str(case["case_key"]): case for case in cases}
    rows: list[dict[str, Any]] = []
    for evaluation in evaluations:
        case = by_case.get(str(evaluation["case_key"]))
        decision = (case or {}).get("final_decision") or {}
        if not isinstance(decision, Mapping) or evaluation.get("excess_return") is None:
            continue
        thesis = decision.get("thesis") or {"open": "positive", "increase": "positive", "reduce": "negative",
                                             "exit": "negative", "avoid": "negative"}.get(str(decision.get("signal")),
                                                                                        "neutral")
        rows.append({
            "horizon": int(evaluation["horizon_days"]),
            "engine_version": str(decision.get("engine_version") or "unknown"),
            "day": str(case.get("as_of_at"))[:10],
            "thesis": thesis,
            "excess": float(evaluation["excess_return"]),
            "brier": evaluation.get("brier_score"),
            "probability_up": decision.get("probability_up"),
            "expected": decision.get("expected_excess_return"),
        })
    horizons: dict[str, Any] = {}
    for horizon, horizon_rows in sorted(_group(rows, "horizon").items(), key=lambda item: int(item[0])):
        horizons[horizon] = {
            "all": _score(horizon_rows),
            "by_engine_version": {version: _score(version_rows)
                                  for version, version_rows in sorted(_group(horizon_rows, "engine_version").items())},
        }
    return {"version": SCORECARD_VERSION, "scored": len(rows), "horizons": horizons}


__all__ = ["SCORECARD_VERSION", "decision_scorecard"]
