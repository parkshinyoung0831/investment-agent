"""Trading이 Research 산출물을 소비하는 단일 공개 계약.

Research 내부의 feature 계산·저장소·모델 serving 구현은 이 경계 뒤에 둔다.
"""
from __future__ import annotations

from typing import Any

from investment_agent.research.datasets.contracts import TrainingSample
from investment_agent.research.evaluation.constants import EVALUATION_HORIZONS
from investment_agent.research.evidence.context import FILING_ROWS_IN_PROMPT, ContextBuilder
from investment_agent.research.evidence.contracts import EvidenceBundle, EvidenceItem
from investment_agent.research.evidence.reader import PitReader, guru_candidate_signals
from investment_agent.research.evidence.statistics import (
    estimate_statistics,
    fundamental_statistics,
    price_statistics,
    quality_statistics,
)
from investment_agent.research.evaluation.costs import TransactionCostModel
from investment_agent.research.features import db as features_db
from investment_agent.research.factors import (
    latest_cross_section,
    percentile_ranks,
    score_cross_section,
)
from investment_agent.research.features.layer import REQUIRED_BARS
from investment_agent.research.ml_serving import (
    NO_FORECAST,
    ChampionForecast,
    champion_forecast,
)
from investment_agent.research.promotion.gate import (
    EvaluationSummary,
    PromotionDecision,
    approval_audit_row,
    has_approved_chain,
)
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


__all__ = [
    "ContextBuilder",
    "EVALUATION_HORIZONS",
    "EvidenceBundle",
    "EvidenceItem",
    "FILING_ROWS_IN_PROMPT",
    "NO_FORECAST",
    "REQUIRED_BARS",
    "ChampionForecast",
    "EvaluationSummary",
    "FeatureSnapshot",
    "ForwardReturnLabel",
    "PitReader",
    "PromotionDecision",
    "TrainingSample",
    "TransactionCostModel",
    "approval_audit_row",
    "champion_forecast",
    "estimate_statistics",
    "guru_candidate_signals",
    "has_approved_chain",
    "fundamental_statistics",
    "latest_cross_section",
    "normalize_symbols",
    "open_research_store",
    "percentile_ranks",
    "price_statistics",
    "quality_statistics",
    "score_cross_section",
    "technical_features_since",
]
