"""yfinance 종목 뉴스 어댑터.

일일 한도는 새로 만들지 않고 `platform.external_usage`의 원장을 쓴다. 두 번째
사용량 계산이 생기면 두 값이 어긋나고, 어긋난 쪽이 항상 실제보다 관대하다.
"""
from __future__ import annotations

from typing import Any

from investment_agent.platform.external_usage import (
    default_ledger_path,
    provider_daily_cap,
    reserve_provider_call,
)
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

PROVIDER = "yfinance"


class NewsQuotaExhausted(RuntimeError):
    """오늘 provider 한도를 다 썼다."""


def fetch_ticker_news(ticker: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """종목 하나의 최근 뉴스 메타데이터를 가져온다."""
    reservation = reserve_provider_call(
        default_ledger_path(),
        provider=PROVIDER,
        cap=provider_daily_cap(PROVIDER),
    )
    if not reservation.allowed:
        raise NewsQuotaExhausted(f"{PROVIDER} daily cap reached ({reservation.cap})")

    import yfinance as yf

    items = yf.Ticker(str(ticker).strip().upper()).news or []
    return [dict(item) for item in items[: int(limit)]]


__all__ = ["NewsQuotaExhausted", "PROVIDER", "fetch_ticker_news"]
