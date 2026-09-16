"""StockTwits 공개 심볼 스트림 fetcher(API 키·OAuth 불필요).

TradingAgents(Apache-2.0) `dataflows/stocktwits.py`에서 이식.
"""
from __future__ import annotations

import http.client
import json
import logging
from typing import Callable
from urllib.request import Request, urlopen

from investment_agent.trading.decision.llm.agents.vendor.symbol_utils import crypto_base

logger = logging.getLogger(__name__)

_API = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
_UA = "investment-agent/1.0"


def _stocktwits_symbol(ticker: str) -> str:
    base = crypto_base(ticker)
    return f"{base}.X" if base else ticker.strip().upper()


def _default_http_get(url: str, headers: dict, timeout: float) -> bytes:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_stocktwits_messages(
    ticker: str,
    limit: int = 30,
    timeout: float = 10.0,
    *,
    http_get: Callable[[str, dict, float], bytes] = _default_http_get,
) -> str:
    """StockTwits 최근 심볼 메시지를 강세/약세 집계와 함께 텍스트로 만든다."""
    url = _API.format(ticker=_stocktwits_symbol(ticker))
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    try:
        raw = http_get(url, headers, timeout)
        data = json.loads(raw)
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        logger.warning("StockTwits fetch failed for %s: %s", ticker, exc)
        return f"<stocktwits unavailable: {type(exc).__name__}>"

    messages = data.get("messages", []) if isinstance(data, dict) else []
    if not messages:
        return f"<no StockTwits messages found for ${ticker.upper()}>"

    lines: list[str] = []
    bullish = bearish = unlabeled = 0
    for message in messages[:limit]:
        created = message.get("created_at", "")
        user = (message.get("user") or {}).get("username", "?")
        entities = message.get("entities") or {}
        sentiment_obj = entities.get("sentiment") or {}
        sentiment = sentiment_obj.get("basic") if isinstance(sentiment_obj, dict) else None
        body = (message.get("body") or "").replace("\n", " ").strip()
        if len(body) > 280:
            body = body[:280] + "…"
        if sentiment == "Bullish":
            bullish += 1
            tag = "Bullish"
        elif sentiment == "Bearish":
            bearish += 1
            tag = "Bearish"
        else:
            unlabeled += 1
            tag = "no-label"
        lines.append(f"[{created} · @{user} · {tag}] {body}")

    total = bullish + bearish + unlabeled
    bull_pct = round(100 * bullish / total) if total else 0
    bear_pct = round(100 * bearish / total) if total else 0
    summary = (
        f"Bullish: {bullish} ({bull_pct}%) · "
        f"Bearish: {bearish} ({bear_pct}%) · "
        f"Unlabeled: {unlabeled} · "
        f"Total: {total} most-recent messages"
    )
    return summary + "\n\n" + "\n".join(lines)
