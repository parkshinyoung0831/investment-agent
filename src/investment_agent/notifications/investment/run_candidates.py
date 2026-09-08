"""신뢰도 상위 종목의 심층 판단 카드를 `#투자-리포트`로 보낸다."""
from __future__ import annotations

import os

from investment_agent.platform.logging import get_logger
from investment_agent.config import load_config
from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.outbox import Outbox
from investment_agent.notifications.service import NotificationService
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.platform.clock import utc_now
from . import embeds
from investment_agent.reporting.notifications.investment import db
from investment_agent.reporting.notifications.connections import configured_database
from .constants import DEFAULT_TOP_N, PIPELINE

log = get_logger(__name__)


def _top_n() -> int:
    raw = os.environ.get("AI_INVESTOR_REPORT_TOP_N", "").strip()
    if not raw:
        return DEFAULT_TOP_N
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("AI_INVESTOR_REPORT_TOP_N must be an integer") from exc
    if not 1 <= value <= 25:
        raise RuntimeError("AI_INVESTOR_REPORT_TOP_N must be between 1 and 25")
    return value


def run(*, service: NotificationService | None = None,
        target: str | None = None) -> int:
    """가장 최근 실행의 상위 후보를 종목별 카드로 보낸다."""
    latest = db.latest_portfolio()
    if latest is None:
        log.info("no decision run to report candidates for")
        return 0

    run_id = str(latest["run"]["run_id"])
    candidates = db.top_candidates(run_id, limit=_top_n())
    if not candidates:
        log.info("no completed candidate to report run_id=%s", run_id)
        return 0

    config = load_config()
    channel_id = discord_target("investment_candidates", config=config, override=target)
    if service is None:
        service = NotificationService(
            Outbox(configured_database(config)), DiscordChannel(config), clock=utc_now,
        )
    sent = 0
    for decision in candidates:
        case_key = str(decision["case_key"])
        key = f"candidate:{case_key}"
        embed = embeds.candidate_embed(decision=decision)
        result = service.enqueue(
            producer=PIPELINE, notification_key=key, kind="candidate",
            target=channel_id, message={"embeds": [embed]},
            entity_key=str(decision.get("ticker") or ""), period_end=str(run_id),
        )
        if result.status == "error":
            continue
        sent += sum(
            1 for item in service.run_pending()
            if item.producer == PIPELINE and item.notification_key == key and item.status == "sent"
        )
    log.info("sent candidate reports run_id=%s sent=%d", run_id, sent)
    return sent


__all__ = ["run"]
