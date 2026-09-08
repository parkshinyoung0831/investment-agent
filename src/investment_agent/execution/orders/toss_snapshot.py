"""토스 미국주식 sleeve를 immutable AccountSnapshot으로 변환한다."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from investment_agent.platform.serialization import parse_datetime
from investment_agent.execution.orders.snapshots import AccountSnapshot, PositionSnapshot
from investment_agent.execution.brokers.toss import client as toss
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.toss_manual import _us_holdings


def capture_toss_account_snapshot(
    *,
    account_seq: int,
    captured_at: datetime | None = None,
    max_quote_age_seconds: float = 120.0,
) -> AccountSnapshot:
    """계좌·보유·미체결·USD 현금·시세를 한 시점 계약으로 묶는다."""
    if not isinstance(account_seq, int) or account_seq <= 0:
        raise ExecutionSafetyError("Toss account_seq must be a positive integer")
    if not math.isfinite(max_quote_age_seconds) or max_quote_age_seconds <= 0:
        raise ExecutionSafetyError("max_quote_age_seconds must be positive")
    now = (captured_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    open_rows = toss.fetch_open_orders(account_seq)
    open_ids: list[str] = []
    for row in open_rows:
        order_id = str(row.get("orderId") or "").strip()
        if not order_id:
            raise ExecutionSafetyError("Toss open order has no orderId")
        open_ids.append(order_id)

    holdings = _us_holdings(toss.fetch_holdings(account_seq))
    prices: dict[str, float] = {}
    timestamps: dict[str, str | None] = {}
    if holdings:
        prices, timestamps = toss.fetch_prices(set(holdings))
    positions: list[PositionSnapshot] = []
    for ticker in sorted(holdings):
        timestamp = timestamps.get(ticker)
        if not timestamp:
            raise ExecutionSafetyError(f"Toss {ticker} quote has no timestamp")
        quote_time = parse_datetime(timestamp)
        age = (now - quote_time).total_seconds()
        if age < 0 or age > max_quote_age_seconds:
            raise ExecutionSafetyError(
                f"Toss {ticker} quote is stale or future-dated: age={age:.3f}s"
            )
        price = float(prices[ticker])
        quantity = float(holdings[ticker])
        positions.append(PositionSnapshot(
            ticker=ticker,
            quantity=quantity,
            market_price=price,
            market_value=quantity * price,
        ))
    cash = toss.fetch_buying_power(account_seq, currency="USD")
    return AccountSnapshot(
        broker="toss",
        account_id=str(account_seq),
        captured_at=now.isoformat(),
        cash_value=cash,
        positions=tuple(positions),
        base_currency="USD",
        open_order_ids=tuple(open_ids),
    )


__all__ = ["capture_toss_account_snapshot"]

