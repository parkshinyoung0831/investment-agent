"""Marcos Lopez de Prado 교수의 Deflated Sharpe Ratio (DSR) 과적합 검정 엔진.

다중 가설 검정(Multiple Testing)과 전략 탐색 횟수(Number of Trials), 수익률의 왜도(Skewness)와
첨도(Kurtosis)를 반영하여, 관측된 샤프 비율이 단순한 데이터 마이닝(오버피팅)의 결과일 확률을 수학적으로 걸러낸다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from investment_agent.platform.serialization import finite_float

_EULER_MASCHERONI = 0.57721566490153286


try:
    from scipy.stats import norm

    def _norm_cdf(x: float) -> float:
        return float(norm.cdf(x))

    def _norm_ppf(p: float) -> float:
        return float(norm.ppf(max(1e-12, min(1.0 - 1e-12, p))))
except ImportError:
    def _norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def _norm_ppf(p: float) -> float:
        p_c = max(1e-12, min(1.0 - 1e-12, p))
        y = 2.0 * p_c - 1.0
        a = 0.147
        term = 2.0 / (math.pi * a) + math.log(1.0 - y * y) / 2.0
        inner = term * term - math.log(1.0 - y * y) / a
        val = math.sqrt(math.sqrt(max(0.0, inner)) - term)
        return (val if y >= 0 else -val) * math.sqrt(2.0)


@dataclass(frozen=True)
class DeflatedSharpeResult:
    """Deflated Sharpe Ratio 검정 결과."""

    observed_sr: float
    expected_max_sr: float
    dsr_probability: float
    is_statistically_significant: bool
    num_trials: int
    sample_length: int
    skewness: float
    kurtosis: float


class DeflatedSharpeRatio:
    """DSR 과적합 통계 검정기."""

    @staticmethod
    def compute(
        returns: Sequence[float],
        num_trials: int = 10,
        benchmark_sr: float = 0.0,
        variance_trials: float = 0.5,
        annualize: bool = True,
        periods_per_year: int = 252,
    ) -> DeflatedSharpeResult:
        """수익률 시계열과 시도 횟수를 바탕으로 DSR 확률을 계산한다."""
        clean_returns = [finite_float(r) for r in returns if finite_float(r) is not None]
        n = len(clean_returns)
        if n < 5:
            return DeflatedSharpeResult(
                observed_sr=0.0, expected_max_sr=0.0, dsr_probability=0.0,
                is_statistically_significant=False, num_trials=num_trials,
                sample_length=n, skewness=0.0, kurtosis=3.0,
            )

        mean_r = sum(clean_returns) / n
        var_r = sum((r - mean_r) ** 2 for r in clean_returns) / (n - 1)
        std_r = math.sqrt(var_r) if var_r > 1e-12 else 1e-6
        ann_factor = math.sqrt(float(periods_per_year)) if annualize else 1.0
        observed_sr = (mean_r / std_r) * ann_factor

        # 왜도(Skewness) 및 첨도(Kurtosis) 계산
        m3 = sum((r - mean_r) ** 3 for r in clean_returns) / n
        m4 = sum((r - mean_r) ** 4 for r in clean_returns) / n
        skew = m3 / (std_r ** 3) if std_r > 1e-6 else 0.0
        kurt = m4 / (std_r ** 4) if std_r > 1e-6 else 3.0

        # 다중 가설 검정 하의 기대 최대 샤프비율 E[max_K {SR_k}]
        k = max(1, int(num_trials))
        if k > 1:
            z1 = _norm_ppf(1.0 - (1.0 / k))
            z2 = _norm_ppf(1.0 - (1.0 / (k * math.e)))
            exp_max_sr = math.sqrt(variance_trials) * ((1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2)
        else:
            exp_max_sr = benchmark_sr

        # 샤프비율의 표준오차 (Mertens 2002 기반)
        var_sr = (1.0 - skew * observed_sr + ((kurt - 1.0) / 4.0) * (observed_sr ** 2)) / (n - 1)
        se_sr = math.sqrt(max(1e-12, var_sr))

        # DSR 통계량 Z와 관측 샤프가 기대 최대 샤프를 넘을 누적확률
        z_stat = (observed_sr - exp_max_sr) / se_sr
        probability = _norm_cdf(z_stat)

        # 95% 신뢰수준(probability >= 0.95) 통과 여부
        is_sig = probability >= 0.95

        return DeflatedSharpeResult(
            observed_sr=round(observed_sr, 4),
            expected_max_sr=round(exp_max_sr, 4),
            dsr_probability=round(probability, 4),
            is_statistically_significant=is_sig,
            num_trials=k,
            sample_length=n,
            skewness=round(skew, 4),
            kurtosis=round(kurt, 4),
        )


__all__ = [
    "DeflatedSharpeRatio",
    "DeflatedSharpeResult",
]
