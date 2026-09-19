"""Trading이 Research 산출물을 소비하는 단일 공개 계약.

Research 내부의 feature 계산·저장소·모델 serving 구현은 이 경계 뒤에 둔다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from investment_agent.research.datasets.contracts import TrainingSample
from investment_agent.research.evaluation.constants import EVALUATION_HORIZONS
from investment_agent.research.evaluation.costs import TransactionCostModel
from investment_agent.research.features import db as features_db
from investment_agent.research.factors import (
    latest_cross_section,
    percentile_ranks,
    score_cross_section,
)
from investment_agent.research.features.layer import FEATURE_VERSION, REQUIRED_BARS
from investment_agent.research.ml_serving import (
    NO_FORECAST,
    ChampionForecast,
    champion_forecast,
)
from investment_agent.research.promotion.gate import EvaluationSummary, PromotionDecision
from investment_agent.research.rl.contracts import (
    FeatureSnapshot,
    ForwardReturnLabel,
    normalize_symbols,
)
from investment_agent.research.storage.repository import ResearchStore


def open_research_store(*, read_only: bool = False) -> ResearchStore:
    """Research DuckDB를 여는 책임은 Research owner에 남긴다."""
    return ResearchStore(read_only=read_only)


def technical_features_since(since: str) -> list[dict[str, Any]]:
    """후보 선정에 필요한 한 창의 기술지표를 반환한다."""
    return features_db.features_since(since)


def latest_technical_signals_as_of(as_of_at: datetime) -> dict[str, dict[str, Any]]:
    """판단 시점에 확정된 종목별 최신 기술지표를 반환한다."""
    return features_db.latest_signals_as_of(as_of_at)


__all__ = [
    "EVALUATION_HORIZONS",
    "FEATURE_VERSION",
    "NO_FORECAST",
    "REQUIRED_BARS",
    "ChampionForecast",
    "EvaluationSummary",
    "FeatureSnapshot",
    "ForwardReturnLabel",
    "PromotionDecision",
    "TrainingSample",
    "TransactionCostModel",
    "champion_forecast",
    "latest_cross_section",
    "latest_technical_signals_as_of",
    "normalize_symbols",
    "open_research_store",
    "percentile_ranks",
    "score_cross_section",
    "technical_features_since",
]
