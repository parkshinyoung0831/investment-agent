"""저장된 판단을 5·20·60 거래일 뒤 SPY 대비 평가한다."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Protocol

from investment_agent.research.evaluation.constants import EVALUATION_HORIZONS
from investment_agent.trading.contracts import EvaluationResult
from investment_agent.trading.evidence.tools import total_return


class EvaluationRepository(Protocol):
    def price_path(self, ticker: str, start_date: date, limit: int = 80) -> list[dict]: ...


def _direction(action: str, excess_return: float) -> bool | None:
    if action in {"open", "increase"}:
        return excess_return > 0
    if action in {"avoid", "reduce", "exit"}:
        return excess_return <= 0
    return None


def evaluate_case(
    repository: EvaluationRepository,
    case: dict,
    *,
    benchmark: str = "SPY",
    horizons: tuple[int, ...] = EVALUATION_HORIZONS,
) -> list[EvaluationResult]:
    as_of = datetime.fromisoformat(str(case["as_of_at"]).replace("Z", "+00:00"))
    decision = case.get("final_decision") or {}
    asset = repository.price_path(str(case["ticker"]), as_of.date(), max(horizons) + 10)
    bench = repository.price_path(benchmark, as_of.date(), max(horizons) + 10)
    if not asset or not bench:
        return []
    asset_by_date = {str(row["trade_date"]): row for row in asset}
    bench_by_date = {str(row["trade_date"]): row for row in bench}
    common_dates = sorted(set(asset_by_date) & set(bench_by_date))
    asset_common = [asset_by_date[key] for key in common_dates]
    bench_common = [bench_by_date[key] for key in common_dates]
    results: list[EvaluationResult] = []
    for horizon in horizons:
        if len(common_dates) <= horizon:
            continue
        asset_return = total_return(asset_common, horizon)
        benchmark_return = total_return(bench_common, horizon)
        excess = asset_return - benchmark_return
        start_close = float(asset_common[0]["close"])
        path_returns = [float(row["close"]) / start_close - 1 for row in asset_common[1:horizon + 1]]
        probability = float(decision.get("probability_up", 0.5))
        outcome = 1.0 if excess > 0 else 0.0
        results.append(EvaluationResult(
            case_key=str(case["case_key"]),
            horizon_days=horizon,
            start_trade_date=common_dates[0],
            end_trade_date=common_dates[horizon],
            asset_return=asset_return,
            benchmark_return=benchmark_return,
            excess_return=excess,
            max_adverse_excursion=min(path_returns),
            max_favorable_excursion=max(path_returns),
            direction_correct=_direction(str(decision.get("action", "watch")), excess),
            brier_score=(probability - outcome) ** 2,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        ))
    return results
