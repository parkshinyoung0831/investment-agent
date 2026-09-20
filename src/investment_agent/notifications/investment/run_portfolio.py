"""하루 한 장의 종합 투자 판단 카드를 `#투자-리포트`로 보낸다."""
from __future__ import annotations

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

log = get_logger(__name__)

TOPIC = topic("ai.portfolio")


def run(*, target: str | None = None, context: PublishContext | None = None) -> int:
    """가장 최근 제안 한 건을 원장에 맡긴다. 이미 보고했으면 원장이 보내지 않는다."""
    latest = db.latest_portfolio()
    if latest is None:
        log.info("no portfolio proposal to report")
        return 0
    proposal, risk, decision_run = latest["proposal"], latest["risk"], latest["run"]
    notice = Notice(
        subject=str(proposal["run_id"]),
        occurrence=str(proposal["proposal_id"]),
        fact_at=fact_time(proposal["as_of_at"]),
        basis={"weights": proposal.get("weights") or {}, "is_approved": risk.get("is_approved")},
    )

    def render(_batch):
        return Rendered({"embeds": [embeds.portfolio_embed(proposal=proposal, risk=risk, run=decision_run)]})

    config = load_config()
    report = publish(
        TOPIC, [notice], render,
        context=context or default_context(config),
        target=discord_target(TOPIC.channel_kind, config=config, override=target),
    )
    return report.delivered


__all__ = ["run"]
