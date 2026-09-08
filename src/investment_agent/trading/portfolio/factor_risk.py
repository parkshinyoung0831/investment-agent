"""다요인(Multi-Factor) 리스크 모델 및 포트폴리오 팩터 익스포저 엔진.

포트폴리오 내 개별 자산의 5대 스타일 팩터(Momentum, Value, Quality, Size, Volatility)
로딩을 계산하고, 포트폴리오 총 팩터 익스포저를 집계하여 특정 스타일로의 과도한 쏠림을 감지한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from investment_agent.platform.serialization import finite_float


@dataclass(frozen=True)
class FactorExposure:
    """개별 자산의 5대 스타일 팩터 로딩 (z-score 정규화 기준, 통상 -3.0 ~ +3.0)."""

    momentum: float = 0.0
    value: float = 0.0
    quality: float = 0.0
    size: float = 0.0
    volatility: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "momentum": self.momentum,
            "value": self.value,
            "quality": self.quality,
            "size": self.size,
            "volatility": self.volatility,
        }


@dataclass(frozen=True)
class PortfolioFactorExposure:
    """포트폴리오 가중 팩터 익스포저."""

    factors: dict[str, float]
    max_absolute_exposure: float
    violations: tuple[str, ...]

    def is_balanced(self, max_limit: float = 1.5) -> bool:
        """어떤 팩터도 허용 한계(기본 1.5 표준편차)를 넘지 않는 균형 상태인가."""
        return self.max_absolute_exposure <= max_limit and len(self.violations) == 0


class FactorRiskEngine:
    """포트폴리오 다요인 리스크 계산 및 제약 검사기."""

    def __init__(self, max_factor_limit: float = 1.5) -> None:
        self.max_factor_limit = max(0.5, float(max_factor_limit))

    def evaluate_portfolio(
        self,
        weights: Mapping[str, float],
        asset_factors: Mapping[str, FactorExposure],
    ) -> PortfolioFactorExposure:
        """자산 비중과 개별 팩터 로딩을 결합하여 포트폴리오 팩터 익스포저를 산출한다."""
        factor_sums = {
            "momentum": 0.0,
            "value": 0.0,
            "quality": 0.0,
            "size": 0.0,
            "volatility": 0.0,
        }

        total_weight = 0.0
        for symbol, raw_weight in weights.items():
            sym = str(symbol).upper().strip()
            if sym == "CASH":
                continue
            w = finite_float(raw_weight) or 0.0
            if w <= 0.0:
                continue
            total_weight += w
            exposure = asset_factors.get(sym, FactorExposure())
            factor_sums["momentum"] += w * exposure.momentum
            factor_sums["value"] += w * exposure.value
            factor_sums["quality"] += w * exposure.quality
            factor_sums["size"] += w * exposure.size
            factor_sums["volatility"] += w * exposure.volatility

        # 정규화: 위험자산 가중합 기준
        norm_factors: dict[str, float] = {}
        max_abs = 0.0
        violations: list[str] = []

        if total_weight > 1e-6:
            for factor_name, weighted_val in factor_sums.items():
                val = weighted_val / total_weight
                norm_factors[factor_name] = round(val, 4)
                abs_val = abs(val)
                if abs_val > max_abs:
                    max_abs = abs_val
                if abs_val > self.max_factor_limit:
                    violations.append(f"{factor_name} ({val:+.2f} > limit ±{self.max_factor_limit:.1f})")
        else:
            norm_factors = {k: 0.0 for k in factor_sums}

        return PortfolioFactorExposure(
            factors=norm_factors,
            max_absolute_exposure=round(max_abs, 4),
            violations=tuple(violations),
        )


__all__ = [
    "FactorExposure",
    "FactorRiskEngine",
    "PortfolioFactorExposure",
]
