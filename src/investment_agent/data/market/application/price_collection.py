"""일봉·기업행위 수집의 공통 절차. daily와 backfill은 대상과 기간만 다르다.

## 종목 신원은 수집을 시작할 때 고정한다

요청할 목록은 `PriceTarget(security_id, symbol)`로 만든다. 공급자는 요청 주소(symbol)로
응답하므로, 응답 행에 security_id를 붙이는 기준은 **그 계획** 하나다. 저장 직전에 ticker를
다시 전역 조회하지 않는다 — 수집 도중 개명·재사용이 반영되면 다른 종목에 쓸 수 있다.

## 순서

계획 고정 → 원문 받기 → security_id 부착(계획에 없는 응답은 거절) → (백필) 원문 archive →
기업행위 병합 → 가격 저장. archive가 실패하면 DB에 쓰지 않는다.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from numbers import Number

from investment_agent.data.market.domain.models import PriceTarget
from investment_agent.data.market.domain.price_repair import is_split_ratio

PRICE_FIELDS = ("open", "high", "low", "close", "volume", "is_repaired")


@dataclass(frozen=True)
class CollectedPrices:
    prices: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    raw_rows: int = 0


def attach_security_ids(raw_rows: Iterable[dict], targets: Sequence[PriceTarget]) -> list[dict]:
    """응답 행에 계획의 security_id를 붙인다. 요청하지 않은 symbol이 오면 실패한다."""
    by_symbol: dict[str, int] = {}
    for target in targets:
        if target.symbol in by_symbol and by_symbol[target.symbol] != target.security_id:
            raise ValueError(f"one request symbol is planned for two securities: {target.symbol}")
        by_symbol[target.symbol] = target.security_id
    rows = []
    unexpected = set()
    for row in raw_rows:
        symbol = str(row["ticker"])
        if symbol not in by_symbol:
            unexpected.add(symbol)
            continue
        rows.append({**row, "security_id": by_symbol[symbol]})
    if unexpected:
        raise RuntimeError(f"provider returned symbols outside the collection plan: {sorted(unexpected)[:10]}")
    return rows


def clean_price_row(row: dict) -> dict:
    """market.prices_daily 저장용으로 기업행위를 뺀 OHLCV 행을 만든다."""
    return {
        "security_id": int(row["security_id"]),
        "trade_date": str(row["trade_date"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": int(row.get("volume") or 0),
        "is_repaired": str(row.get("source") or "yfinance") == "yfinance_repaired",
    }


def action_rows(raw_rows: Iterable[dict]) -> list[dict]:
    """응답 행에서 그날의 분할·배당을 한 행으로 모은다. 없는 값은 싣지 않는다(병합이 보존)."""
    merged: dict[tuple[int, str], dict] = {}
    for row in raw_rows:
        key = (int(row["security_id"]), str(row["trade_date"]))
        action: dict = {}
        ratio = row.get("split_ratio")
        if is_split_ratio(ratio):
            action["split_ratio"] = float(ratio)
        amount = row.get("div_amount")
        try:
            value = float(amount) if amount is not None else None
        except (TypeError, ValueError):
            value = None
        if value is not None and math.isfinite(value) and value > 0:
            action["dividend_amount"] = value
            action["dividend_currency"] = "USD"
        if not action:
            continue
        current = merged.setdefault(key, {
            "security_id": key[0], "action_date": key[1],
            "source": str(row.get("source") or "yfinance").replace("_repaired", ""),
        })
        current.update(action)
    return [merged[key] for key in sorted(merged)]


def _same_value(left, right) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, Number) and isinstance(right, Number):
        return math.isclose(float(left), float(right), rel_tol=1e-10, abs_tol=1e-10)
    return str(left) == str(right)


def changed_prices(rows: Iterable[dict], existing: dict[tuple[int, str], dict]) -> list[dict]:
    """새 키이거나 저장된 값과 다른 가격 행만 돌려준다."""
    changed = []
    for row in rows:
        current = existing.get((int(row["security_id"]), str(row["trade_date"])))
        if current is None or any(not _same_value(row.get(f), current.get(f)) for f in PRICE_FIELDS):
            changed.append(row)
    return changed


def collect_prices(
    targets: Sequence[PriceTarget],
    *,
    lookback_days: int,
    download: Callable[[list[str], int], list[dict]],
    archive: Callable[[list[dict]], object] | None = None,
) -> CollectedPrices:
    """계획대로 받아 가격·기업행위 행으로 나눈다. 빈 응답은 실패다."""
    if not targets:
        return CollectedPrices()
    raw = download([target.symbol for target in targets], lookback_days)
    if not raw:
        raise RuntimeError(f"price provider returned no rows for {len(targets)} planned securities")
    rows = attach_security_ids(raw, targets)
    if archive is not None:
        archive(rows)
    return CollectedPrices(
        prices=[clean_price_row(row) for row in rows],
        actions=action_rows(rows),
        raw_rows=len(rows),
    )


__all__ = [
    "PRICE_FIELDS", "CollectedPrices", "PriceTarget", "action_rows", "attach_security_ids",
    "changed_prices", "clean_price_row", "collect_prices",
]
