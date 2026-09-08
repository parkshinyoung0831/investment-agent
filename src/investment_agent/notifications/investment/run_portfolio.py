"""하루 한 장의 종합 투자 판단 카드를 `#투자-리포트`로 보낸다."""
from __future__ import annotations


from investment_agent.platform.logging import get_logger
from investment_agent.config import load_config
from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.outbox import Outbox
from investment_agent.notifications.service import NotificationService
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.platform.clock import utc_now
from . import embeds
from investment_agent.reporting.notifications.connections import configured_database
from investment_agent.reporting.notifications.investment import db
from .constants import PIPELINE

log = get_logger(__name__)


def run(*, service: NotificationService | None = None,
        target: str | None = None) -> int:
    """가장 최근 제안 한 건을 카드로 보낸다. 이미 보고했으면 아무것도 하지 않는다."""
    latest = db.latest_portfolio()
    if latest is None:
        log.info("no portfolio proposal to report")
        return 0

    proposal, risk, decision_run = latest["proposal"], latest["risk"], latest["run"]
    proposal_id = str(proposal["proposal_id"])
    key = f"portfolio:{proposal_id}"
    embed = embeds.portfolio_embed(proposal=proposal, risk=risk, run=decision_run)
    config = load_config()
    channel_id = discord_target("investment_portfolio", config=config, override=target)
    if service is None:
        service = NotificationService(
            Outbox(configured_database(config)), DiscordChannel(config), clock=utc_now,
        )
    result = service.enqueue(
        producer=PIPELINE, notification_key=key, kind="portfolio",
        target=channel_id, message={"embeds": [embed]},
        entity_key=str(proposal["run_id"]), period_end=str(proposal["as_of_at"]),
    )
    if result.status == "error":
        return 0
    sent = sum(
        1 for item in service.run_pending()
        if item.producer == PIPELINE and item.notification_key == key and item.status == "sent"
    )
    log.info("portfolio report finished proposal_id=%s sent=%d", proposal_id, sent)
    return sent


__all__ = ["run"]
