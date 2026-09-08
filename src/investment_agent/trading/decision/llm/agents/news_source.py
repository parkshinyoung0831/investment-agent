"""TradingAgents News Analyst를 위한 실시간 뉴스(yfinance/Alpha Vantage) 데이터 소스 어댑터."""
from __future__ import annotations

import os
from typing import Callable

from investment_agent.trading.contracts import EvidenceBundle, parse_datetime
from investment_agent.platform.external_usage import provider_daily_cap

_EXTERNAL_NEWS_VENDOR = "ai_external_news"


def _symbol_ok(symbol: str, bundle: EvidenceBundle) -> bool:
    return str(symbol).upper() == bundle.ticker


def _date_ok(value: str | None, bundle: EvidenceBundle) -> bool:
    if not value:
        return True
    try:
        requested = str(value)[:10]
        return requested <= parse_datetime(bundle.as_of_at).date().isoformat()
    except (TypeError, ValueError):
        return False


def validate_news_vendor_config(requested_vendor: str) -> str:
    """선택한 upstream news vendor의 필수 설정을 네트워크 호출 전에 검증한다."""
    vendor = str(requested_vendor).strip().lower()
    if vendor in {"", "supabase", _EXTERNAL_NEWS_VENDOR}:
        raise RuntimeError("AI_INVESTOR_TRADINGAGENTS_NEWS_VENDOR must name one upstream news vendor")
    if vendor == "alpha_vantage" and not os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip():
        raise RuntimeError(
            "ALPHA_VANTAGE_API_KEY is required when the TradingAgents news vendor "
            "is alpha_vantage"
        )
    provider_daily_cap(vendor)
    return vendor


def fetch_external_news(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    requested_vendor: str,
    get_bundle: Callable[[], EvidenceBundle],
    external_fetch: Callable[..., str],
    record_external: Callable[..., str],
    upstream_fetcher: Callable[..., str] | None,
) -> str:
    """종목별 실시간 뉴스를 공급자(yfinance / Alpha Vantage)에서 수집한다."""
    bundle = get_bundle()
    request = {"ticker": str(ticker).upper(), "start_date": start_date, "end_date": end_date}
    if not _symbol_ok(ticker, bundle) or not _date_ok(end_date, bundle):
        return record_external(
            domain="news",
            provider=requested_vendor,
            request=request,
            raw="DATA_UNAVAILABLE: ticker/date is outside the active point-in-time bundle",
            status="blocked",
        )
    return external_fetch(
        domain="news",
        provider=requested_vendor,
        request=request,
        fetch=(lambda: upstream_fetcher(ticker, start_date, end_date)) if upstream_fetcher else None,
    )


def fetch_external_global_news(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
    *,
    requested_vendor: str,
    get_bundle: Callable[[], EvidenceBundle],
    external_fetch: Callable[..., str],
    record_external: Callable[..., str],
    upstream_fetcher: Callable[..., str] | None,
) -> str:
    """시장 전반의 실시간 글로벌 뉴스를 수집한다."""
    bundle = get_bundle()
    request = {
        "curr_date": curr_date,
        "look_back_days": look_back_days,
        "limit": limit,
    }
    if not _date_ok(curr_date, bundle):
        return record_external(
            domain="news",
            provider=requested_vendor,
            request=request,
            raw="DATA_UNAVAILABLE: requested global-news date is after as_of_at",
            status="blocked",
        )
    return external_fetch(
        domain="news",
        provider=requested_vendor,
        request=request,
        fetch=(lambda: upstream_fetcher(curr_date, look_back_days, limit)) if upstream_fetcher else None,
    )
