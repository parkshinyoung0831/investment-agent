"""실제 주문·체결 기록을 `#매매-기록`으로 보낸다. 체결이 진행되면 같은 카드를 고친다."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from investment_agent.config import load_config
from investment_agent.notifications.context import default_context
from investment_agent.notifications.engine import (
    Notice,
    PublishContext,
    Rendered,
    fact_time,
    publish,
)
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.notifications.topics import topic
from investment_agent.platform.logging import get_logger
from investment_agent.reporting.notifications.investment import db

from . import embeds
from .constants import DEFAULT_TRADE_LOOKBACK_HOURS

log = get_logger(__name__)

TOPIC = topic("ai.trade")


def _lookback_hours() -> int:
    raw = os.environ.get("AI_INVESTOR_TRADE_LOOKBACK_HOURS", "").strip()
    if not raw:
        return DEFAULT_TRADE_LOOKBACK_HOURS
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("AI_INVESTOR_TRADE_LOOKBACK_HOURS must be an integer") from exc
    if not 1 <= value <= 168:
        raise RuntimeError("AI_INVESTOR_TRADE_LOOKBACK_HOURS must be between 1 and 168")
    return value


def notices(trades: list[dict]) -> list[Notice]:
    """주문 하나 = 카드 하나. 내용은 주문 상태와 체결 누계다 — 바뀌면 그 카드를 고친다."""
    out = []
    for trade in trades:
        order = trade["order"]
        fills = trade.get("fills") or ()
        out.append(Notice(
            subject=str(order.get("ticker") or order["client_order_id"]),
            occurrence=str(order["client_order_id"]),
            fact_at=fact_time(order.get("submitted_at") or order.get("updated_at")),
            basis={
                "status": order.get("status"),
                "filled_quantity": sum(float(fill.get("quantity") or 0.0) for fill in fills),
                "fills": len(fills),
            },
            data=trade,
        ))
    return out


def render(batch) -> Rendered:
    trade = batch[0].data
    return Rendered({"embeds": [embeds.trade_embed(
        order=trade["order"], fills=trade.get("fills") or (),
        execution_mode=str(trade.get("execution_mode") or "unknown"),
    )]})


def run(*, target: str | None = None, context: PublishContext | None = None) -> int:
    """되돌아본 구간의 주문을 원장에 맡긴다."""
    since = datetime.now(timezone.utc) - timedelta(hours=_lookback_hours())
    trades = db.recent_orders(since_at=since.isoformat())
    if not trades:
        log.info("no order to report since %s", since.isoformat())
        return 0
    config = load_config()
    report = publish(
        TOPIC, notices(trades), render,
        context=context or default_context(config),
        target=discord_target(TOPIC.channel_kind, config=config, override=target),
    )
    return report.delivered


__all__ = ["run"]
