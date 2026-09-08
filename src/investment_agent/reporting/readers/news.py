"""Dashboard가 사용할 화면 결과를 intelligence 뉴스 provider 결과로 변환한다."""

from __future__ import annotations

from investment_agent.intelligence.infrastructure.sources.news import provider
from investment_agent.reporting.models import DataResult


def _as_data_result(result: provider.NewsResult) -> DataResult:
    """provider 결과를 reporting 공통 조회 상태로 변환한다."""

    return DataResult(
        status=result.status,
        rows=result.rows,
        source=result.source,
        observed_at=result.observed_at,
        message=result.message,
    )


def load_live_news(query: str, ticker: str | None = None) -> DataResult:
    """명시적 화면 동작용 뉴스 조회 결과를 reporting 계약으로 반환한다."""

    return _as_data_result(provider.load_live_news(query, ticker=ticker))


def provider_statuses() -> DataResult:
    """뉴스 provider 정책 상태를 reporting 계약으로 반환한다."""

    return _as_data_result(provider.provider_statuses())

__all__ = ["load_live_news", "provider_statuses"]
