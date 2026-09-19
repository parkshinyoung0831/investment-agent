"""투자 개념 factor의 계산·계약 경계.

feature는 관측 원재료를 만들고, 이 패키지는 그것을 품질·가치·모멘텀 같은
횡단면 투자 개념으로 점수화한다.
"""
from __future__ import annotations

from investment_agent.research.factors.core import (
    FACTOR_CATEGORIES,
    SECTOR_RELATIVE_CATEGORIES,
    FactorModel,
    FactorScore,
    feature_rows_by_ticker,
    latest_cross_section,
    load_factor_model_from_ic_report,
    percentile_ranks,
    rank_candidates,
    score_cross_section,
)

__all__ = [
    "FACTOR_CATEGORIES",
    "SECTOR_RELATIVE_CATEGORIES",
    "FactorModel",
    "FactorScore",
    "feature_rows_by_ticker",
    "latest_cross_section",
    "load_factor_model_from_ic_report",
    "percentile_ranks",
    "rank_candidates",
    "score_cross_section",
]
