"""yfinance 기반 종목별 뉴스 fetcher.

TradingAgents(Apache-2.0) `dataflows/yfinance_news.py`에서 이식(그래프·LLM 의존
없는 순수 fetcher만). 전역/거시 뉴스 검색(`get_global_news_yfinance`)은 옮기지
않았다 — Macro Analyst가 구조화된 Supabase 거시지표를 이미 다루므로 자유 텍스트
검색이 중복이었다. rate-limit 재시도(`yf_retry`)와 `get_config()` 의존은 이
저장소 규모에 맞춰 고정 상수로 단순화했다.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from investment_agent.trading.decision.llm.agents.vendor.symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)

_ARTICLE_LIMIT = 20
_MAX_RETRIES = 3
_BASE_DELAY_SECONDS = 2.0


def _default_ticker_factory(symbol: str) -> Any:
    import yfinance as yf

    return yf.Ticker(symbol)


def _yf_retry(func: Callable[[], Any]) -> Any:
    """yfinance 호출 하나를 rate limit(429)에 지수 backoff로 재시도한다."""
    from yfinance.exceptions import YFRateLimitError

    for attempt in range(_MAX_RETRIES + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt >= _MAX_RETRIES:
                raise
            delay = _BASE_DELAY_SECONDS * (2 ** attempt)
            logger.warning("Yahoo Finance rate limited, retrying in %.0fs", delay)
            time.sleep(delay)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _extract_article_data(article: dict) -> dict:
    if "content" in article:
        content = article["content"]
        provider = content.get("provider", {})
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        pub_date = None
        pub_date_str = content.get("pubDate", "")
        if pub_date_str:
            try:
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pub_date = None
        return {
            "title": content.get("title", "No title"),
            "summary": content.get("summary", ""),
            "publisher": provider.get("displayName", "Unknown"),
            "link": url_obj.get("url", ""),
            "pub_date": pub_date,
        }
    pub_date = None
    timestamp = article.get("providerPublishTime")
    if timestamp:
        try:
            pub_date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (ValueError, OSError, TypeError):
            pub_date = None
    return {
        "title": article.get("title", "No title"),
        "summary": article.get("summary", ""),
        "publisher": article.get("publisher", "Unknown"),
        "link": article.get("link", ""),
        "pub_date": pub_date,
    }


def _in_news_window(pub_date: datetime | None, start_dt: datetime, end_dt: datetime) -> bool:
    end = _as_utc(end_dt)
    if pub_date is not None:
        return _as_utc(start_dt) <= _as_utc(pub_date) < end + timedelta(days=1)
    return end >= datetime.now(timezone.utc) - timedelta(days=1)


def get_news_yfinance(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    ticker_factory: Callable[[str], Any] = _default_ticker_factory,
    article_limit: int = _ARTICLE_LIMIT,
) -> str:
    """yfinance에서 종목 뉴스를 가져와 [start_date, end_date] 창으로 걸러 텍스트로 만든다."""
    canonical = normalize_symbol(ticker)
    resolved = "" if canonical == ticker else f" (resolved to {canonical})"
    try:
        stock = ticker_factory(canonical)
        news = _yf_retry(lambda: stock.get_news(count=article_limit))
        if not news:
            return f"No news found for {ticker}{resolved}"

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        news_text = ""
        kept = 0
        for article in news:
            data = _extract_article_data(article)
            if not _in_news_window(data["pub_date"], start_dt, end_dt):
                continue
            news_text += f"### {data['title']} (source: {data['publisher']})\n"
            if data["summary"]:
                news_text += f"{data['summary']}\n"
            if data["link"]:
                news_text += f"Link: {data['link']}\n"
            news_text += "\n"
            kept += 1

        if kept == 0:
            return f"No news found for {ticker}{resolved} between {start_date} and {end_date}"
        return f"## {ticker}{resolved} News, from {start_date} to {end_date}:\n\n{news_text}"
    except Exception as exc:  # noqa: BLE001 - 외부 provider 경계, 실패는 텍스트로 보고한다
        return f"Error fetching news for {ticker}: {exc}"
