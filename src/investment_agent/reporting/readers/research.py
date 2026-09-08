"""Research 산출물을 presentation 계층에 노출하는 읽기 계약."""
from __future__ import annotations

from typing import Any

from investment_agent.research.storage.repository import ResearchStore
from investment_agent.reporting.services.strategy_labels import strategy_ids, strategy_label


def load_local_features(ticker: str, *, limit: int = 520) -> list[dict[str, Any]]:
    """로컬 기술지표 read model을 화면 표시용 행으로 반환한다."""
    return ResearchStore(read_only=True).features_for_ticker(ticker, limit=limit)


def load_local_strategy_data() -> dict[str, list[dict[str, Any]]]:
    """코드 카탈로그와 로컬 전략 배분을 화면 계약으로 결합한다."""
    strategies: list[dict[str, Any]] = []
    for strategy_id in strategy_ids():
        label = strategy_label(strategy_id)
        if label is not None:
            strategies.append({
                "id": label.strategy_id,
                "name": label.name,
                "description": label.description,
                "created_at": None,
            })
    return {"strategies": strategies, "allocations": ResearchStore(read_only=True).allocations()}


def load_local_research_records(dataset: str) -> list[dict[str, Any]]:
    """Research DuckDB의 dataset을 dashboard read model로 노출한다."""
    return ResearchStore(read_only=True).records(dataset)


__all__ = ["load_local_features", "load_local_research_records", "load_local_strategy_data"]
