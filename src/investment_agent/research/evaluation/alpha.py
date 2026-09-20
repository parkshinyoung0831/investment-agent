"""예측이 종목 **순위**로 쓸 만한지 날짜별 단면으로 평가한다.

RMSE는 예측 숫자가 얼마나 맞는지를 보지만, 포트폴리오가 쓰는 것은 "어느 종목을 더
사고 덜 사는가"다. 그래서 같은 날짜 안에서 예측 순위와 실현 순위의 상관(IC)을 날짜마다
구하고, 그 평균(IC)·안정성(ICIR)·상위-하위 분위 수익차(spread)를 본다. 날짜를 섞어
한 번에 상관을 구하면 시장 전체가 오른 날의 공통 움직임이 순위 능력처럼 부풀려진다.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Hashable, Sequence

import numpy as np

IC_INFERENCE_METHOD = "newey_west_bartlett_iid_floor_v1"

@dataclass(frozen=True)
class CrossSectionalAlphaScore:
    date_count: int
    mean_ic: float
    ic_std: float
    icir: float
    ic_t_stat: float
    positive_ic_ratio: float
    mean_quantile_spread: float
    quantiles: int
    observation_count: int
    ic_t_stat_iid: float
    inference_method: str
    horizon_days: int
    hac_lags: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rank(values: np.ndarray) -> np.ndarray:
    """동점은 평균 순위로 둔다. argsort 두 번은 동점을 입력 순서로 갈라 IC를 흔든다."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    sorted_values = values[order]
    start = 0
    while start < len(values):
        end = start
        while end + 1 < len(values) and sorted_values[end + 1] == sorted_values[start]:
            end += 1
        ranks[order[start:end + 1]] = (start + end) / 2.0
        start = end + 1
    return ranks


def spearman_ic(actual: Sequence[float], predicted: Sequence[float]) -> float | None:
    """한 날짜 단면의 순위 상관. 한쪽 순위가 전부 같으면 정의되지 않는다."""
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    if len(a) != len(p) or len(a) < 3:
        return None
    ra, rp = _rank(a), _rank(p)
    if np.std(ra) == 0 or np.std(rp) == 0:
        return None
    return float(np.corrcoef(ra, rp)[0, 1])


def cross_sectional_alpha_metrics(
    dates: Sequence[Hashable],
    actual: Sequence[float],
    predicted: Sequence[float],
    *,
    quantiles: int = 5,
    min_names_per_date: int = 5,
    horizon_days: int = 1,
) -> CrossSectionalAlphaScore:
    """날짜별 IC와 분위 spread를 모아 한 모델의 순위 능력을 요약한다."""
    if not len(dates) == len(actual) == len(predicted) or not dates:
        raise ValueError("dates, actual and predicted must have the same non-empty length")
    if quantiles < 2 or min_names_per_date < quantiles:
        raise ValueError("min_names_per_date must be at least quantiles and quantiles >= 2")
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or horizon_days < 1:
        raise ValueError("horizon_days must be a positive integer")
    grouped: dict[Hashable, list[tuple[float, float]]] = defaultdict(list)
    for key, left, right in zip(dates, actual, predicted, strict=True):
        value_actual, value_predicted = float(left), float(right)
        if not math.isfinite(value_actual) or not math.isfinite(value_predicted):
            raise ValueError("alpha evaluation values must be finite")
        grouped[key].append((value_actual, value_predicted))

    ics: list[float] = []
    spreads: list[float] = []
    used = 0
    # 숫자 날짜 키도 시간 순서여야 한다(문자열 정렬의 1,10,2는 자기상관을 훼손한다).
    for key in sorted(grouped):
        rows = grouped[key]
        if len(rows) < min_names_per_date:
            continue
        a = np.asarray([row[0] for row in rows], dtype=float)
        p = np.asarray([row[1] for row in rows], dtype=float)
        ic = spearman_ic(a, p)
        if ic is None:
            continue
        ics.append(ic)
        used += len(rows)
        # 예측 순위로 나눈 분위의 실현 평균: 최상위 분위 - 최하위 분위.
        buckets = np.array_split(np.argsort(_rank(p), kind="mergesort"), quantiles)
        spreads.append(float(np.mean(a[buckets[-1]]) - np.mean(a[buckets[0]])))

    if not ics:
        raise ValueError("no date has enough distinct names to compute an IC")
    values = np.asarray(ics, dtype=float)
    mean_ic = float(values.mean())
    ic_std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    icir = mean_ic / ic_std if ic_std > 0 else 0.0
    # 겹치는 h일 label의 IC를 독립 표본으로 세면 유효 표본 수가 부풀려진다.
    # Bartlett HAC(h-1), 유한표본 n/(n-1) 보정. 음의 자기상관으로 채택 근거가
    # 더 강해지지 않도록 IID 평균분산을 하한으로 둔다. 이는 확률 calibration은 아니다.
    count = len(values)
    lags = min(horizon_days - 1, count - 1)
    residual = values - mean_ic
    variance_sum = float(residual @ residual)
    for lag in range(1, lags + 1):
        variance_sum += 2.0 * (1.0 - lag / (lags + 1)) * float(residual[lag:] @ residual[:-lag])
    mean_variance = max(ic_std ** 2 / count, variance_sum / (count * (count - 1))) if count > 1 else 0.0
    t_stat = mean_ic / math.sqrt(mean_variance) if mean_variance > 0 and count > horizon_days else 0.0
    return CrossSectionalAlphaScore(
        date_count=len(values),
        mean_ic=mean_ic,
        ic_std=ic_std,
        icir=icir,
        ic_t_stat=t_stat,
        positive_ic_ratio=float(np.mean(values > 0)),
        mean_quantile_spread=float(np.mean(spreads)),
        quantiles=quantiles,
        observation_count=used,
        ic_t_stat_iid=icir * math.sqrt(count),
        inference_method=IC_INFERENCE_METHOD,
        horizon_days=horizon_days,
        hac_lags=lags,
    )


__all__ = ["IC_INFERENCE_METHOD", "CrossSectionalAlphaScore", "cross_sectional_alpha_metrics", "spearman_ic"]
