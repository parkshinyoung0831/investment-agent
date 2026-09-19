"""Reddit 공개 검색 RSS(Atom) 기반 종목 언급 fetcher(API 키 불필요).

TradingAgents(Apache-2.0) `dataflows/reddit.py`에서 이식. JSON 검색 엔드포인트는
공개 클라이언트에 WAF로 막혀 있어(업스트림 이슈 #862) 상시 RSS-first 경로만
이식했다 — JSON 경로는 업스트림에서도 기본으로 쓰지 않는다.
"""
from __future__ import annotations

import html
import http.client
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Callable, Iterable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from investment_agent.trading.decision.llm.agents.vendor.symbol_utils import crypto_base

logger = logging.getLogger(__name__)

_RSS = "https://www.reddit.com/r/{sub}/search.rss?{qs}"
_UA = "investment-agent/1.0"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")


def _search_qs(ticker: str, limit: int) -> str:
    return urlencode({
        "q": ticker, "restrict_sr": "on", "sort": "new", "t": "week", "limit": limit,
    })


def _iso_to_timestamp(iso_str: str | None) -> float | None:
    if not iso_str:
        return None
    try:
        normalized = iso_str[:-1] + "+00:00" if iso_str.endswith("Z") else iso_str
        return datetime.fromisoformat(normalized).timestamp()
    except (ValueError, TypeError):
        return None


def _strip_html(content: str) -> str:
    if not content:
        return ""
    if "<!-- SC_OFF -->" in content and "<!-- SC_ON -->" in content:
        content = content.split("<!-- SC_OFF -->")[1].split("<!-- SC_ON -->")[0]
    text = re.sub(r"<[^>]+>", " ", content)
    return " ".join(html.unescape(text).split())


def _retry_after_seconds(exc: HTTPError) -> float | None:
    try:
        value = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
        return min(float(value), 30.0) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def _default_http_get(url: str, headers: dict, timeout: float) -> bytes:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _fetch_subreddit(
    ticker: str, sub: str, limit: int, timeout: float, *,
    http_get: Callable[[str, dict, float], bytes],
    sleep: Callable[[float], None],
    retry: bool = True,
) -> list[dict]:
    url = _RSS.format(sub=sub, qs=_search_qs(ticker, limit))
    try:
        root = ET.fromstring(http_get(url, {"User-Agent": _UA}, timeout))
    except HTTPError as exc:
        if exc.code == 429 and retry:
            wait = _retry_after_seconds(exc) or 5.0
            logger.warning("Reddit RSS 429 for r/%s · %s — backing off %.1fs", sub, ticker, wait)
            sleep(wait)
            return _fetch_subreddit(
                ticker, sub, limit, timeout, http_get=http_get, sleep=sleep, retry=False,
            )
        logger.warning("Reddit RSS fetch failed for r/%s · %s: %s", sub, ticker, exc)
        return []
    except (OSError, http.client.HTTPException, ET.ParseError) as exc:
        logger.warning("Reddit RSS fetch failed for r/%s · %s: %s", sub, ticker, exc)
        return []

    posts = []
    for entry in root.findall("atom:entry", _ATOM_NS)[:limit]:
        title_el = entry.find("atom:title", _ATOM_NS)
        published_el = entry.find("atom:published", _ATOM_NS)
        content_el = entry.find("atom:content", _ATOM_NS)
        posts.append({
            "title": (title_el.text if title_el is not None else "") or "",
            "created_utc": _iso_to_timestamp(published_el.text if published_el is not None else None),
            "selftext": _strip_html(content_el.text if content_el is not None else ""),
        })
    return posts


def fetch_reddit_posts(
    ticker: str,
    subreddits: Iterable[str] = DEFAULT_SUBREDDITS,
    limit_per_sub: int = 5,
    timeout: float = 10.0,
    inter_request_delay: float = 1.0,
    *,
    http_get: Callable[[str, dict, float], bytes] = _default_http_get,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """finance 서브레딧에서 최근 종목 언급 게시물을 검색해 텍스트로 만든다."""
    ticker = crypto_base(ticker) or ticker
    blocks = []
    total_posts = 0
    for index, sub in enumerate(subreddits):
        if index > 0:
            sleep(inter_request_delay)
        posts = _fetch_subreddit(
            ticker, sub, limit_per_sub, timeout, http_get=http_get, sleep=sleep,
        )
        total_posts += len(posts)
        if not posts:
            blocks.append(f"r/{sub}: <no posts found mentioning {ticker.upper()} in the past 7 days>")
            continue

        lines = [f"r/{sub} — {len(posts)} recent posts mentioning {ticker.upper()} (via RSS feed):"]
        for post in posts:
            title = (post.get("title") or "").replace("\n", " ").strip()
            created = post.get("created_utc")
            created_str = time.strftime("%Y-%m-%d", time.gmtime(created)) if created else "?"
            selftext = (post.get("selftext") or "").replace("\n", " ").strip()
            if len(selftext) > 240:
                selftext = selftext[:240] + "…"
            lines.append(
                f"  [{created_str}] {title}" + (f"\n    body excerpt: {selftext}" if selftext else "")
            )
        blocks.append("\n".join(lines))

    if total_posts == 0:
        subs_text = ", ".join(f"r/{sub}" for sub in subreddits)
        return f"<no Reddit posts found mentioning {ticker.upper()} across {subs_text} in the past 7 days>"
    return "\n\n".join(blocks)
