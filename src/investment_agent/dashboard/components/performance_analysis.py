"""성과 화면의 위험 조정 지표와 고점 회복 구간을 계산한다."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from investment_agent.dashboard.calculations import _return_series, performance_metrics


def risk_metrics(
    returns: pd.Series, *, periods_per_year: int = 12, annual_risk_free: float = 0.0,
    min_observations: int = 12,
) -> dict[str, Any]:
    """단순 수익률 기준. Sortino는 전체 관측의 하방편차, 무위험수익률은 복리 변환한다."""
    series = _return_series(returns)
    result = dict.fromkeys(("sharpe", "sortino", "calmar", "hit_rate"))
    result["observations"] = len(series)
    if periods_per_year < 1 or not math.isfinite(annual_risk_free) or annual_risk_free <= -1:
        return result
    if len(series) < max(2, min_observations):
        return result
    excess = series - ((1.0 + annual_risk_free) ** (1.0 / periods_per_year) - 1.0)
    deviation = float(excess.std(ddof=1))
    downside = float(np.sqrt(np.minimum(excess, 0.0).pow(2).mean()))
    scale = math.sqrt(periods_per_year)
    if deviation > 1e-12:
        result["sharpe"] = float(excess.mean()) / deviation * scale
    if downside > 1e-12:
        result["sortino"] = float(excess.mean()) / downside * scale
    metrics = performance_metrics(series, periods_per_year=periods_per_year)
    depth = metrics["max_drawdown"]
    if depth is not None and depth < -1e-12:
        result["calmar"] = metrics["cagr"] / abs(depth)
    result["hit_rate"] = float((series > 0).mean())
    return result


def drawdown_series(returns: pd.Series) -> pd.Series:
    """초기 자산 1을 고점에 포함해 첫 관측부터의 손실도 표시한다."""
    series = _return_series(returns)
    wealth = (1.0 + series).cumprod()
    return (wealth / wealth.cummax().clip(lower=1.0) - 1.0).rename("drawdown")


def drawdown_episodes(returns: pd.Series, *, limit: int = 5) -> list[dict[str, Any]]:
    """깊은 순으로 고점·저점·회복 관측을 반환한다. 미회복은 recovery=None이다."""
    series = _return_series(returns)
    if series.empty or limit < 1:
        return []
    wealth = (1.0 + series).cumprod()
    peak_value, peak_index = 1.0, -1
    active: dict[str, Any] | None = None
    episodes: list[dict[str, Any]] = []
    for index, (label, value) in enumerate(wealth.items()):
        depth = float(value / peak_value - 1.0)
        if value >= peak_value or math.isclose(float(value), peak_value, rel_tol=1e-12):
            if active is not None:
                active.update(recovery=label, periods=index - peak_index, is_recovered=True)
                episodes.append(active)
                active = None
            peak_value, peak_index = float(value), index
        else:
            if active is None:
                active = {"peak": series.index[peak_index] if peak_index >= 0 else None,
                          "trough": label, "depth": depth, "recovery": None,
                          "periods": index - peak_index, "is_recovered": False}
            if depth < active["depth"]:
                active.update(trough=label, depth=depth)
            active["periods"] = index - peak_index
    if active is not None:
        episodes.append(active)
    return sorted(episodes, key=lambda row: row["depth"])[:limit]
