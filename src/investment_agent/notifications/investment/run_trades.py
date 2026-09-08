"""실제 주문·체결 기록을 `#매매-기록`으로 보낸다."""
from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from investment_agent.platform.logging import get_logger
from investment_agent.config import load_config
from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.outbox import Outbox
from investment_agent.notifications.service import NotificationService
from investment_agent.notifications.subscriptions import discord_targets
from investment_agent.platform.clock import utc_now
from . import embeds
from investment_agent.reporting.notifications.investment import db
from investment_agent.reporting.notifications.connections import configured_database
from .constants import DEFAULT_TRADE_LOOKBACK_HOURS, PIPELINE

log = get_logger(__name__)


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


def run(*, service: NotificationService | None = None,
        targets: Sequence[str] | None = None) -> int:
    """되돌아본 구간에서 아직 보고하지 않은 주문을 카드로 보낸다."""
    since = datetime.now(timezone.utc) - timedelta(hours=_lookback_hours())
    trades = db.recent_orders(since_at=since.isoformat())
    if not trades:
        log.info("no order to report since %s", since.isoformat())
        return 0

    config = load_config()
    target_ids = tuple(targets) if targets is not None else discord_targets(
        "investment_trades", config=config
    )
    if len(target_ids) != 1:
        raise RuntimeError("investment_trades requires exactly one Discord subscription target")
    channel_id = target_ids[0]
    if service is None:
        service = NotificationService(
            Outbox(configured_database(config)), DiscordChannel(config), clock=utc_now,
        )
    sent = 0
    for trade in trades:
        order = trade["order"]
        order_id = str(order["client_order_id"])
        key = f"trade:{order_id}"
        embed = embeds.trade_embed(
            order=order,
            fills=trade.get("fills") or (),
            execution_mode=str(trade.get("execution_mode") or "unknown"),
        )
        result = service.enqueue(
            producer=PIPELINE, notification_key=key, kind="trade",
            target=channel_id, message={"embeds": [embed]},
            entity_key=str(order.get("ticker") or ""), period_end=str(order.get("updated_at") or ""),
        )
        if result.status == "error":
            continue
        sent += sum(
            1 for item in service.run_pending()
            if item.producer == PIPELINE and item.notification_key == key and item.status == "sent"
        )
    log.info("sent trade reports sent=%d", sent)
    return sent


__all__ = ["run"]
