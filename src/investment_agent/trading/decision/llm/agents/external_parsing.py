"""provider 응답 blob을 기사·게시물 단위 ExternalContent로 쪼갠다.

upstream TradingAgents는 항목 여럿을 마크다운 한 덩어리로 돌려준다. 그대로 저장하면
중복제거가 덩어리 단위로만 걸리고 기사별 조회도 불가능해서, 저장 직전 여기서 쪼갠다.
포맷을 알아보지 못하면 덩어리 하나를 그대로 돌려준다 — 저장이 끊기는 것보다 낫다.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from investment_agent.trading.contracts import parse_datetime
from investment_agent.trading.evidence.cache import ExternalContent

# "### <title> (source: <publisher>)" — yfinance news formatter의 항목 경계다.
_ARTICLE_HEADING = re.compile(r"^###\s+(?P<title>.+?)(?:\s+\(source:\s*(?P<source>[^)]*)\))?\s*$")
_LINK_LINE = re.compile(r"^Link:\s*(?P<url>\S+)\s*$")
# "[<시각> · @<작성자> · <태그>] <본문>"(StockTwits)과
# "[<날짜> · <점수> · <댓글수>] <제목>"(Reddit)의 공통 항목 경계다.
_MESSAGE_LINE = re.compile(r"^\[(?P<meta>[^\]]+)\]\s*(?P<body>.*)$")
# "r/<subreddit> ..." 는 다음 블록의 시작이라 앞 게시물에 이어 붙이지 않는다.
_SOCIAL_BLOCK_BOUNDARY = re.compile(r"^r/\S+")
_TAG_SENTIMENT = {"bullish": 1.0, "bearish": -1.0}
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean(value: str) -> str:
    return " ".join(str(value).split()).strip()


def _ticker_of(request: Mapping[str, Any]) -> str | None:
    raw = request.get("ticker") or request.get("symbol")
    return str(raw).upper().strip() or None if raw else None


def _parse_markdown_articles(
    raw: str,
    *,
    provider: str,
    symbol: str | None,
    fetched_at: str,
) -> list[ExternalContent]:
    """`### 제목 (source: 매체)` / 본문 / `Link: URL` 블록을 항목별로 나눈다."""
    items: list[ExternalContent] = []
    title: str | None = None
    source: str | None = None
    url: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal title, source, url, body
        if title:
            summary = _clean(" ".join(body))
            items.append(ExternalContent(
                provider=provider,
                content_type="news",
                symbol=symbol,
                published_at=None,  # upstream 포맷이 기사별 발행시각을 담지 않는다
                fetched_at=fetched_at,
                url=url,
                title=title,
                content=summary or title,
                source=source,
            ))
        title, source, url, body = None, None, None, []

    for line in raw.splitlines():
        heading = _ARTICLE_HEADING.match(line.strip())
        if heading:
            flush()
            title = _clean(heading.group("title"))
            source = _clean(heading.group("source") or "") or None
            continue
        if title is None:
            continue
        link = _LINK_LINE.match(line.strip())
        if link:
            url = link.group("url")
            continue
        if line.strip():
            body.append(line.strip())
    flush()
    return items


def _safe_published_at(value: str, fetched_at: str) -> str | None:
    """미래로 찍힌 provider 시각은 버린다 — 저장 자체가 막히는 편이 더 나쁘다."""
    text = _clean(value)
    # Reddit은 날짜만 주므로 그 날의 UTC 자정으로 읽는다. 시각을 지어내지 않는 가장 이른 값이다.
    if _DATE_ONLY.match(text):
        text = f"{text}T00:00:00+00:00"
    try:
        published = parse_datetime(text)
    except (TypeError, ValueError):
        return None
    return published.isoformat() if published <= parse_datetime(fetched_at) else None


def _split_message_meta(meta: str) -> tuple[str, str | None, float | None]:
    """`시각 · @작성자 · 태그` 머리말을 시각·작성자·감성으로 나눈다."""
    parts = [_clean(part) for part in meta.split("·")]
    published_at = parts[0] if parts else ""
    author: str | None = None
    sentiment: float | None = None
    for part in parts[1:]:
        if part.startswith("@"):
            author = part[1:] or None
            continue
        if sentiment is None:
            sentiment = _TAG_SENTIMENT.get(part.lower())
    return published_at, author, sentiment


def _parse_bracketed_messages(
    raw: str,
    *,
    provider: str,
    symbol: str | None,
    fetched_at: str,
) -> list[ExternalContent]:
    """대괄호 머리말이 붙은 게시물을 항목별로 나눈다. 이어지는 줄은 앞 글에 붙인다."""
    items: list[ExternalContent] = []
    meta: tuple[str, str | None, float | None] | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal meta, body
        if meta is not None:
            text = _clean(" ".join(body))
            if text:
                published_at, author, sentiment = meta
                items.append(ExternalContent(
                    provider=provider,
                    content_type="social",
                    symbol=symbol,
                    published_at=_safe_published_at(published_at, fetched_at),
                    fetched_at=fetched_at,
                    url=None,
                    title=None,
                    content=text,
                    author=author,
                    source=provider,
                    sentiment=sentiment,
                ))
        meta, body = None, []

    for line in raw.splitlines():
        stripped = line.strip()
        match = _MESSAGE_LINE.match(stripped)
        if match:
            flush()
            meta = _split_message_meta(match.group("meta"))
            body = [match.group("body")]
            continue
        if _SOCIAL_BLOCK_BOUNDARY.match(stripped):
            flush()
            continue
        if meta is not None and stripped:
            body.append(stripped)
    flush()
    return items


def parse_external_payload(
    *,
    domain: str,
    provider: str,
    request: Mapping[str, Any],
    raw: str,
    fetched_at: str,
) -> tuple[ExternalContent, ...]:
    """한 provider 응답을 저장 가능한 항목들로 쪼갠다. 못 쪼개면 덩어리 하나로 둔다."""
    symbol = _ticker_of(request)
    content_type = "social" if domain == "social" else "news"
    if content_type == "social":
        items = _parse_bracketed_messages(
            raw, provider=provider, symbol=symbol, fetched_at=fetched_at
        )
    else:
        items = _parse_markdown_articles(
            raw, provider=provider, symbol=symbol, fetched_at=fetched_at
        )
    if items:
        return tuple(items)
    return (ExternalContent(
        provider=provider,
        content_type=content_type,
        symbol=symbol,
        published_at=None,
        fetched_at=fetched_at,
        url=None,
        title=None,
        content=raw,
        source=provider,
    ),)


__all__ = ["parse_external_payload"]
