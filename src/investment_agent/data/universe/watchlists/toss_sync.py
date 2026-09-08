"""토스 보유종목 스냅샷을 통합 관심종목에 반영한다."""
from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from typing import Any

from investment_agent.data.universe.watchlists import db
from investment_agent.data.universe.infrastructure.sources import toss_holdings as toss

_ASSET_RATE_LIMIT_DELAY = 0.25


def normalize_toss_symbol(symbol: str) -> str:
    """토스 미국 심볼(BRK.B)을 universe 표준(BRK-B)으로 바꾼다."""
    normalized = symbol.strip().upper().replace(".", "-")
    if not normalized:
        raise toss.TossApiError("토스 보유종목에 빈 symbol이 있습니다")
    return normalized


def held_us_tickers(items: list[dict[str, Any]]) -> list[str]:
    """정상적인 양수 미국 주식 보유분의 티커만 중복 없이 반환한다.

    수량이나 필수 필드가 깨진 항목은 무시하지 않고 실패시킨다. 스키마 변경을
    빈 스냅샷으로 오인해 기존 관심종목을 해제하지 않기 위한 안전장치다.
    """
    tickers: set[str] = set()
    for item in items:
        country = item.get("marketCountry")
        symbol = item.get("symbol")
        quantity = item.get("quantity")
        if not isinstance(country, str) or not isinstance(symbol, str):
            raise toss.TossApiError("토스 보유종목에 marketCountry 또는 symbol이 없습니다")
        try:
            parsed_quantity = Decimal(str(quantity))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise toss.TossApiError("토스 보유종목 quantity가 올바르지 않습니다") from exc
        if parsed_quantity < 0:
            raise toss.TossApiError("토스 보유종목 quantity가 음수입니다")
        if country.upper() == "US" and parsed_quantity > 0:
            tickers.add(normalize_toss_symbol(symbol))
    return sorted(tickers)


def collect_toss_holdings() -> tuple[list[str], dict[str, int]]:
    """모든 토스 종합매매 계좌의 미국 주식 보유종목을 합친다."""
    accounts = toss.fetch_accounts()
    all_items: list[dict[str, Any]] = []
    for index, account in enumerate(accounts):
        if index:
            time.sleep(_ASSET_RATE_LIMIT_DELAY)
        all_items.extend(toss.fetch_holdings(int(account["accountSeq"])))
    tickers = held_us_tickers(all_items)
    return tickers, {
        "accounts": len(accounts),
        "holding_items": len(all_items),
        "us_tickers": len(tickers),
    }


def sync_toss_holdings(*, dry_run: bool = False) -> dict[str, Any]:
    """토스 전체 스냅샷 조회가 성공한 뒤 기존 관심종목의 출처만 갱신한다."""
    tickers, collected = collect_toss_holdings()
    if dry_run:
        return {**collected, "dry_run": True, "tickers": tickers}
    result = db.sync_toss_members(tickers)
    return {**collected, "dry_run": False, **result}
