"""뉴스 provider 호출과 원문 보존 없는 화면용 메타데이터 정규화."""

from __future__ import annotations

import html
import math
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from investment_agent.platform.cache import cache_data
from investment_agent.intelligence.domain.contracts import NewsResult


def sanitize_message(value: object, *, fallback: str = "요청을 처리하지 못했습니다.") -> str:
    """뉴스 화면에 노출할 텍스트에서 URL·자격증명처럼 위험한 값을 제거한다."""

    text = " ".join(str(value or "").split()) or fallback
    text = re.sub(r"https?://\S+", "[URL 숨김]", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|authorization|password)\b\s*[:=]\s*[^\s,;]+",
        lambda match: f"{match.group(1)}=[숨김]",
        text,
    )
    return text[:400]


def public_exception_message(prefix: str, error: BaseException) -> str:
    """예외 본문 대신 안전한 오류 유형만 뉴스 결과에 포함한다."""

    return sanitize_message(f"{prefix} ({type(error).__name__})")


LIVE_SOURCE_YFINANCE = "실시간 조회 · yfinance"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_NEWS_ALLOWLIST = frozenset({"yfinance"})


_BLOCKED_SOCIAL = frozenset({"stocktwits", "reddit"})
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,14}$")


def _offline_mode() -> bool:
    return os.environ.get("DASHBOARD_OFFLINE", "").strip().lower() in _TRUE_VALUES


def _news_enabled() -> bool:
    return (
        os.environ.get("AI_INVESTOR_EXTERNAL_NEWS_SOCIAL", "true").strip().lower()
        in _TRUE_VALUES
    )


def _canonical_url(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = urlsplit(text)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))


def _news_time(value: object) -> str | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return sanitize_message(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _sentiment_and_risk(title: str, summary: str) -> tuple[str, list[str]]:
    text = f"{title} {summary}".lower()
    positive = ("beat", "growth", "upgrade", "surge", "record", "profit", "상향", "성장", "호조")
    negative = ("miss", "downgrade", "loss", "fall", "cut", "probe", "하향", "손실", "부진")
    positive_score = sum(word in text for word in positive)
    negative_score = sum(word in text for word in negative)
    sentiment = "긍정" if positive_score > negative_score else "부정" if negative_score > positive_score else "불확실"
    risk_terms = {
        "규제": ("regulation", "regulator", "antitrust", "규제"),
        "소송": ("lawsuit", "litigation", "court", "소송"),
        "실적": ("earnings", "revenue", "profit", "guidance", "실적"),
        "매크로": ("inflation", "rates", "fed", "recession", "금리", "침체"),
        "지정학": ("war", "sanction", "geopolit", "전쟁", "제재"),
    }
    tags = [label for label, words in risk_terms.items() if any(word in text for word in words)]
    return sentiment, tags


def _normalized_news_item(item: Mapping[str, Any], ticker: str | None) -> dict[str, Any] | None:
    content = item.get("content") if isinstance(item.get("content"), Mapping) else item
    assert isinstance(content, Mapping)
    provider = content.get("provider")
    provider_name = (
        provider.get("displayName") if isinstance(provider, Mapping) else provider
    )
    canonical = content.get("canonicalUrl") or content.get("clickThroughUrl")
    raw_url = canonical.get("url") if isinstance(canonical, Mapping) else canonical
    raw_url = raw_url or content.get("link") or content.get("url")
    title = html.unescape(str(content.get("title") or "").strip())
    summary = html.unescape(
        str(content.get("summary") or content.get("description") or "").strip()
    )
    url = _canonical_url(raw_url)
    if not title or not url:
        return None
    title = sanitize_message(title)[:240]
    summary = sanitize_message(summary, fallback="")[:500]
    published_at = _news_time(
        content.get("pubDate")
        or content.get("providerPublishTime")
        or content.get("published_at")
    )
    related_value = (
        content.get("relatedTickers")
        or content.get("related_tickers")
        or item.get("relatedTickers")
        or item.get("related_tickers")
        or ()
    )
    if isinstance(related_value, str):
        related_candidates: Sequence[object] = (related_value,)
    elif isinstance(related_value, Sequence):
        related_candidates = related_value
    else:
        related_candidates = ()
    related_tickers = list(
        dict.fromkeys(
            symbol
            for value in (*related_candidates, ticker)
            if value not in (None, "")
            for symbol in [str(value).strip().upper()]
            if _TICKER_RE.fullmatch(symbol)
        )
    )
    sentiment, risk_tags = _sentiment_and_risk(title, summary)
    return {
        "title": title,
        "source": sanitize_message(provider_name or "Yahoo Finance"),
        "published_at": published_at,
        "url": url,
        "summary": summary or None,
        "ticker": ticker,
        "related_tickers": related_tickers,
        "sentiment": sentiment,
        "risk_tags": risk_tags,
        "analysis_use": "참고용",
        "provider": "yfinance",
    }


@cache_data(ttl="5m", max_entries=32)
def load_live_news(query: str, ticker: str | None = None) -> NewsResult:
    """명시적 UI 동작에서만 yfinance 뉴스 한도를 예약하고 짧은 메타데이터를 읽는다."""

    if _offline_mode():
        return NewsResult.offline(source=LIVE_SOURCE_YFINANCE)
    if not _news_enabled():
        return NewsResult.blocked(
            source=LIVE_SOURCE_YFINANCE,
            message="외부 뉴스·소셜 kill switch가 꺼져 있습니다.",
        )
    provider = os.environ.get("DASHBOARD_NEWS_PROVIDER", "yfinance").strip().lower()
    if provider in _BLOCKED_SOCIAL:
        return NewsResult.blocked(
            source=f"실시간 조회 · {provider}",
            message="승인된 수집 adapter가 없어 이 provider는 호출하지 않습니다.",
        )
    if provider not in _NEWS_ALLOWLIST:
        return NewsResult.blocked(
            source=f"실시간 조회 · {provider or '미지정'}",
            message="대시보드 뉴스 provider allowlist에 없는 공급자입니다.",
        )
    search_query = " ".join(str(query or "").split())
    symbol = str(ticker or "").strip().upper() or None
    if not search_query:
        return NewsResult.blocked(source=LIVE_SOURCE_YFINANCE, message="뉴스 검색 주제가 필요합니다.")
    if len(search_query) > 120:
        return NewsResult.blocked(source=LIVE_SOURCE_YFINANCE, message="뉴스 검색어가 너무 깁니다.")
    if symbol and not _TICKER_RE.fullmatch(symbol):
        return NewsResult.blocked(source=LIVE_SOURCE_YFINANCE, message="유효한 종목 코드가 필요합니다.")
    try:
        from investment_agent.platform.external_usage import (
            default_ledger_path,
            provider_daily_cap,
            reserve_provider_call,
        )

        cap = provider_daily_cap("yfinance")
        reservation = reserve_provider_call(
            default_ledger_path(),
            provider="yfinance",
            cap=cap,
        )
        if not reservation.allowed:
            return NewsResult.blocked(
                source=LIVE_SOURCE_YFINANCE,
                message=f"yfinance 일일 사용량 cap({reservation.cap})에 도달했습니다.",
            )

        import yfinance as yf

        lookup = f"{symbol} {search_query}" if symbol else search_query
        raw_items = yf.Search(
            lookup,
            max_results=0,
            news_count=12,
            lists_count=0,
            include_cb=False,
            include_nav_links=False,
            include_research=False,
            include_cultural_assets=False,
            recommended=0,
            timeout=20,
            raise_errors=True,
        ).news
        if not isinstance(raw_items, list):
            raw_items = []
        rows = [
            normalized
            for item in raw_items
            if isinstance(item, Mapping)
            for normalized in [_normalized_news_item(item, symbol)]
            if normalized is not None
        ]
        rows.sort(key=lambda row: str(row.get("published_at") or ""), reverse=True)
        observed_at = next(
            (row.get("published_at") for row in rows if row.get("published_at")),
            datetime.now(timezone.utc).isoformat(),
        )
        usage_note = (
            f"사용량 {reservation.attempts}/{reservation.cap}; 원문 저장 없음; AI 입력 아님"
        )
        if not rows:
            return NewsResult.empty(
                source=LIVE_SOURCE_YFINANCE,
                observed_at=observed_at,
                message=f"검색 결과가 없습니다. {usage_note}",
            )
        return NewsResult.ok(
            rows=rows,
            source=LIVE_SOURCE_YFINANCE,
            observed_at=observed_at,
            message=usage_note,
        )
    except Exception as error:
        return NewsResult.error(
            source=LIVE_SOURCE_YFINANCE,
            message=public_exception_message("뉴스 조회 또는 사용량 원장 확인에 실패했습니다.", error),
        )


@cache_data(ttl="30s", max_entries=2)
def provider_statuses() -> NewsResult:
    """네트워크 호출 없이 뉴스·소셜 provider의 사용 가능 정책을 설명한다."""

    offline = _offline_mode()
    news_enabled = _news_enabled()
    selected = os.environ.get("DASHBOARD_NEWS_PROVIDER", "yfinance").strip().lower()
    social_raw = os.environ.get("AI_INVESTOR_EXTERNAL_SOCIAL_VENDORS", "")
    enabled_social = {item.strip().lower() for item in social_raw.split(",") if item.strip()}
    stocktwits_approved = (
        os.environ.get("STOCKTWITS_API_ACCESS_APPROVED", "false").strip().lower()
        in _TRUE_VALUES
    )

    stocktwits_status = (
        "offline"
        if offline
        else "available"
        if (news_enabled and "stocktwits" in enabled_social and stocktwits_approved)
        else "blocked"
    )
    stocktwits_reason = (
        "DASHBOARD_OFFLINE"
        if offline
        else "실시간 심볼 스트림 사용 가능"
        if stocktwits_status == "available"
        else "kill switch 꺼짐"
        if not news_enabled
        else "승인 API 또는 서면 권한을 확인한 adapter 없음"
    )
    stocktwits_use = (
        "AI 분석에 사용 가능" if stocktwits_status == "available" else "사용 불가 provider"
    )

    reddit_status = (
        "offline"
        if offline
        else "available"
        if (news_enabled and "reddit" in enabled_social)
        else "blocked"
    )
    reddit_reason = (
        "DASHBOARD_OFFLINE"
        if offline
        else "실시간 검색 피드 사용 가능"
        if reddit_status == "available"
        else "kill switch 꺼짐"
        if not news_enabled
        else "AI_INVESTOR_EXTERNAL_SOCIAL_VENDORS 미설정"
    )
    reddit_use = (
        "AI 분석에 사용 가능" if reddit_status == "available" else "사용 불가 provider"
    )

    finnhub_has_key = bool(os.environ.get("FINNHUB_API_KEY", "").strip())
    finnhub_status = (
        "offline"
        if offline
        else "available"
        if (news_enabled and "finnhub" in enabled_social and finnhub_has_key)
        else "blocked"
    )
    finnhub_reason = (
        "DASHBOARD_OFFLINE"
        if offline
        else "실시간 소셜 감성(정량) 사용 가능"
        if finnhub_status == "available"
        else "kill switch 꺼짐"
        if not news_enabled
        else "FINNHUB_API_KEY 미설정 또는 AI_INVESTOR_EXTERNAL_SOCIAL_VENDORS 미포함"
    )
    finnhub_use = (
        "AI 분석에 사용 가능" if finnhub_status == "available" else "사용 불가 provider"
    )

    rows = [
        {
            "provider": "yfinance",
            "kind": "news",
            "status": (
                "offline" if offline else "blocked" if not news_enabled or selected != "yfinance" else "available"
            ),
            "analysis_use": "참고용",
            "reason": (
                "DASHBOARD_OFFLINE" if offline else "kill switch 또는 provider 선택" if not news_enabled or selected != "yfinance" else "명시적 검색 시 cap 예약 후 호출"
            ),
        },
        {
            "provider": "alpha_vantage",
            "kind": "news",
            "status": "blocked",
            "analysis_use": "사용 불가 provider",
            "reason": "대시보드 직접 adapter 미구현",
        },
        {
            "provider": "stocktwits",
            "kind": "social",
            "status": stocktwits_status,
            "analysis_use": stocktwits_use,
            "reason": stocktwits_reason,
        },
        {
            "provider": "reddit",
            "kind": "social",
            "status": reddit_status,
            "analysis_use": reddit_use,
            "reason": reddit_reason,
        },
        {
            "provider": "finnhub",
            "kind": "social",
            "status": finnhub_status,
            "analysis_use": finnhub_use,
            "reason": finnhub_reason,
        },
    ]
    return NewsResult.ok(rows=rows, source="화면 정책 계산 · provider allowlist")


__all__ = [
    "load_live_news",
    "provider_statuses",
]
