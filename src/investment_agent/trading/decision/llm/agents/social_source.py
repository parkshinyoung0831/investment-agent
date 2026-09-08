"""TradingAgents Social Analyst를 위한 소셜 미디어(StockTwits/Reddit) 센티먼트 데이터 소스 어댑터."""
from __future__ import annotations

import os
from typing import Callable

from investment_agent.platform.external_usage import provider_daily_cap

_SUPPORTED_SOCIAL_VENDORS = frozenset({"stocktwits", "reddit", "finnhub"})


def enabled_social_vendors() -> frozenset[str]:
    """공식 API 접근 및 일일 한도를 준비한 provider만 명시적으로 활성화한다."""
    raw = os.environ.get("AI_INVESTOR_EXTERNAL_SOCIAL_VENDORS", "")
    enabled = frozenset(item.strip().lower() for item in raw.split(",") if item.strip())
    unknown = sorted(enabled - _SUPPORTED_SOCIAL_VENDORS)
    if unknown:
        raise RuntimeError(
            "unsupported AI_INVESTOR_EXTERNAL_SOCIAL_VENDORS: " + ", ".join(unknown)
        )
    if "stocktwits" in enabled and os.environ.get(
        "STOCKTWITS_API_ACCESS_APPROVED", "false"
    ).strip().lower() != "true":
        raise RuntimeError(
            "StockTwits live collection requires approved API access or written permission; "
            "set STOCKTWITS_API_ACCESS_APPROVED=true only after that approval"
        )
    if "finnhub" in enabled and not os.environ.get("FINNHUB_API_KEY", "").strip():
        raise RuntimeError("FINNHUB_API_KEY is required when finnhub is in AI_INVESTOR_EXTERNAL_SOCIAL_VENDORS")
    for provider in sorted(enabled):
        provider_daily_cap(provider)
    return enabled


def fetch_stocktwits_messages(
    ticker: str,
    limit: int = 30,
    *,
    external_fetch: Callable[..., str],
    record_external: Callable[..., str],
    upstream_fetcher: Callable[[str, int], str],
) -> str:
    """StockTwits 최근 심볼 메시지 스트림을 수집한다."""
    request = {"ticker": str(ticker).upper(), "limit": int(limit)}
    if "stocktwits" not in enabled_social_vendors():
        return record_external(
            domain="social",
            provider="stocktwits",
            request=request,
            raw=(
                "DATA_UNAVAILABLE: StockTwits is not enabled. Official API access or written "
                "permission must be confirmed before live use."
            ),
            status="blocked",
        )
    return external_fetch(
        domain="social",
        provider="stocktwits",
        request=request,
        fetch=lambda: upstream_fetcher(ticker, limit=limit),
    )


def fetch_reddit_posts(
    ticker: str,
    *,
    external_fetch: Callable[..., str],
    record_external: Callable[..., str],
    upstream_fetcher: Callable[[str], str],
) -> str:
    """Reddit 토론 검색 피드를 수집한다."""
    request = {"ticker": str(ticker).upper(), "window": "current_week"}
    if "reddit" not in enabled_social_vendors():
        return record_external(
            domain="social",
            provider="reddit",
            request=request,
            raw=(
                "DATA_UNAVAILABLE: Reddit is not enabled. Registered OAuth access and an "
                "identifying User-Agent are required before live use."
            ),
            status="blocked",
        )
    return external_fetch(
        domain="social",
        provider="reddit",
        request=request,
        fetch=lambda: upstream_fetcher(ticker),
    )


def fetch_finnhub_sentiment(
    ticker: str,
    *,
    external_fetch: Callable[..., str],
    record_external: Callable[..., str],
) -> str:
    """Finnhub 소셜 감성(Reddit/Twitter 멘션 및 긍부정 스코어) 정량 데이터를 수집한다."""
    request = {"ticker": str(ticker).upper(), "source": "social-sentiment"}
    if "finnhub" not in enabled_social_vendors():
        return record_external(
            domain="social",
            provider="finnhub",
            request=request,
            raw="DATA_UNAVAILABLE: finnhub is not in AI_INVESTOR_EXTERNAL_SOCIAL_VENDORS",
            status="blocked",
        )

    def _call_finnhub() -> str:
        import httpx
        api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
        url = f"https://finnhub.io/api/v1/stock/social-sentiment?symbol={ticker.upper()}&token={api_key}"
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text

    return external_fetch(
        domain="social",
        provider="finnhub",
        request=request,
        fetch=_call_finnhub,
    )


def patch_sentiment_fetchers(
    *,
    external_fetch: Callable[..., str],
    record_external: Callable[..., str],
) -> Callable[[], None]:
    """TradingAgents의 StockTwits/Reddit sentiment fetcher를 안전한 live gate로 패치한다."""
    from tradingagents.agents.analysts import sentiment_analyst

    original_stocktwits = sentiment_analyst.fetch_stocktwits_messages
    original_reddit = sentiment_analyst.fetch_reddit_posts

    def stocktwits(ticker: str, limit: int = 30) -> str:
        return fetch_stocktwits_messages(
            ticker,
            limit=limit,
            external_fetch=external_fetch,
            record_external=record_external,
            upstream_fetcher=original_stocktwits,
        )

    def reddit(ticker: str) -> str:
        return fetch_reddit_posts(
            ticker,
            external_fetch=external_fetch,
            record_external=record_external,
            upstream_fetcher=original_reddit,
        )

    sentiment_analyst.fetch_stocktwits_messages = stocktwits
    sentiment_analyst.fetch_reddit_posts = reddit

    def restore() -> None:
        sentiment_analyst.fetch_stocktwits_messages = original_stocktwits
        sentiment_analyst.fetch_reddit_posts = original_reddit

    return restore
