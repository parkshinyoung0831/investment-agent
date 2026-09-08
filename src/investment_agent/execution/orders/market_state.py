"""실시간 quote를 보관하는 단일 프로세스 RAM Hot State."""
from __future__ import annotations

import math
import threading
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from investment_agent.platform.serialization import canonical_json, json_value, parse_datetime


def _number(value: Any, field_name: str, *, allow_none: bool = True) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    return parsed


@dataclass(frozen=True)
class MarketQuote:
    """주문 직전 사용할 수 있는 최신 ticker quote."""

    ticker: str
    bid: float | None
    ask: float | None
    last: float | None
    mid: float | None
    spread: float | None
    spread_bps: float | None
    volume: float | None
    recent_volume: float | None
    volatility: float | None
    halted: bool
    session: str
    observed_at: str

    def __post_init__(self) -> None:
        ticker = str(self.ticker).upper().strip()
        if not ticker or ticker == "CASH":
            raise ValueError("quote ticker is required")
        values = {}
        for name in (
            "bid", "ask", "last", "mid", "spread", "spread_bps", "volume",
            "recent_volume", "volatility",
        ):
            value = _number(getattr(self, name), name)
            if value is not None and name in {"bid", "ask", "last", "mid", "spread", "spread_bps", "volume", "recent_volume", "volatility"} and value < 0.0:
                raise ValueError(f"{name} must be non-negative")
            values[name] = value
        if values["bid"] is not None and values["ask"] is not None and values["ask"] < values["bid"]:
            raise ValueError("ask cannot be below bid")
        if not isinstance(self.halted, bool) or not str(self.session).strip():
            raise ValueError("halted and session are required")
        observed = parse_datetime(self.observed_at).astimezone(timezone.utc).isoformat()
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "observed_at", observed)
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_snapshot_row(
        self,
        *,
        purpose: str,
        source_kind: str = "paper",
        captured_at: str | datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """판단·주문·체결·reconciliation 순간에만 저장할 durable quote row."""
        if purpose not in {"pre_decision", "pre_order", "submitted", "fill", "reconciliation"}:
            raise ValueError("invalid quote snapshot purpose")
        if source_kind not in {"backtest", "live_shadow", "paper", "live"}:
            raise ValueError("invalid quote snapshot source_kind")
        captured = parse_datetime(captured_at or datetime.now(timezone.utc)).isoformat()
        payload = {
            "ticker": self.ticker,
            "purpose": purpose,
            "source_kind": source_kind,
            "quote": self.to_dict(),
            "captured_at": captured,
            "metadata": dict(metadata or {}),
        }
        snapshot_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return {
            "snapshot_id": f"quote_{snapshot_hash[:24]}",
            "ticker": self.ticker,
            "purpose": purpose,
            "source_kind": source_kind,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "mid": self.mid,
            "spread": self.spread,
            "spread_bps": self.spread_bps,
            "volume": self.volume,
            "recent_volume": self.recent_volume,
            "volatility": self.volatility,
            "halted": self.halted,
            "session": self.session,
            "observed_at": self.observed_at,
            "captured_at": captured,
            "metadata": json_value(dict(metadata or {})),
            "snapshot_hash": snapshot_hash,
        }


class MarketState:
    """최신값만 덮어쓰는 RAM cache. source of truth나 주문 ledger가 아니다."""

    def __init__(self) -> None:
        self._quotes: dict[str, MarketQuote] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _quote_from_values(
        ticker: str,
        *,
        bid: float | None = None,
        ask: float | None = None,
        last: float | None = None,
        mid: float | None = None,
        volume: float | None = None,
        recent_volume: float | None = None,
        volatility: float | None = None,
        halted: bool = False,
        session: str = "unknown",
        observed_at: str | datetime,
    ) -> MarketQuote:
        if mid is None and bid is not None and ask is not None:
            mid = (float(bid) + float(ask)) / 2.0
        if mid is None:
            mid = last
        spread = None if bid is None or ask is None else float(ask) - float(bid)
        spread_bps = None if spread is None or mid in (None, 0) else spread / float(mid) * 10_000.0
        return MarketQuote(
            ticker=ticker,
            bid=bid,
            ask=ask,
            last=last,
            mid=mid,
            spread=spread,
            spread_bps=spread_bps,
            volume=volume,
            recent_volume=recent_volume,
            volatility=volatility,
            halted=halted,
            session=session,
            observed_at=parse_datetime(observed_at).isoformat(),
        )

    def update(self, quote: MarketQuote | None = None, **values: Any) -> MarketQuote:
        """최신 quote를 원자적으로 교체한다."""
        if quote is None:
            if "ticker" not in values or "observed_at" not in values:
                raise ValueError("ticker and observed_at are required")
            quote = self._quote_from_values(**values)
        if not isinstance(quote, MarketQuote):
            raise TypeError("update requires MarketQuote")
        with self._lock:
            previous = self._quotes.get(quote.ticker)
            if previous is not None and parse_datetime(quote.observed_at) < parse_datetime(previous.observed_at):
                raise ValueError("older quote cannot overwrite newer MarketState")
            self._quotes[quote.ticker] = quote
        return quote

    def get(self, ticker: str) -> MarketQuote | None:
        with self._lock:
            return self._quotes.get(str(ticker).upper().strip())

    def snapshot(self) -> Mapping[str, MarketQuote]:
        """호출자가 수정할 수 없는 정렬된 shallow snapshot을 반환한다."""
        with self._lock:
            return dict(sorted(self._quotes.items()))

    def is_fresh(self, ticker: str, *, as_of_at: str | datetime, max_age_seconds: float = 30.0) -> bool:
        if max_age_seconds <= 0.0 or not math.isfinite(float(max_age_seconds)):
            raise ValueError("max_age_seconds must be positive")
        quote = self.get(ticker)
        if quote is None:
            return False
        now = parse_datetime(as_of_at)
        observed = parse_datetime(quote.observed_at)
        return observed <= now and (now - observed).total_seconds() <= max_age_seconds

    def require_fresh(self, ticker: str, *, as_of_at: str | datetime, max_age_seconds: float = 30.0) -> MarketQuote:
        quote = self.get(ticker)
        if quote is None or not self.is_fresh(ticker, as_of_at=as_of_at, max_age_seconds=max_age_seconds):
            raise RuntimeError(f"fresh market quote unavailable for {str(ticker).upper()}")
        if quote.halted:
            raise RuntimeError(f"market quote is halted for {quote.ticker}")
        return quote


__all__ = ["MarketQuote", "MarketState"]
