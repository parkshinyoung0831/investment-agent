"""신뢰도 상위 종목의 심층 판단 카드를 `#투자-리포트`로 보낸다."""
from __future__ import annotations

import os

from investment_agent.config import load_config
from investment_agent.notifications.engine import (
    Notice,
    PublishContext,
    Rendered,
    default_context,
    fact_time,
    publish,
)
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.notifications.topics import topic
from investment_agent.platform.logging import get_logger
from investment_agent.reporting.notifications.investment import db

from . import embeds
from .constants import DEFAULT_TOP_N

log = get_logger(__name__)

TOPIC = topic("ai.candidate")


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


def run(*, target: str | None = None, context: PublishContext | None = None) -> int:
    """가장 최근 실행의 상위 후보를 종목별 카드로 원장에 맡긴다."""
    latest = db.latest_portfolio()
    if latest is None:
        log.info("no decision run to report candidates for")
        return 0
    run_id = str(latest["run"]["run_id"])
    decisions = db.top_candidates(run_id, limit=_top_n())
    if not decisions:
        log.info("no completed candidate to report run_id=%s", run_id)
        return 0
    notices = [
        Notice(
            subject=str(decision.get("ticker") or decision["case_key"]),
            occurrence=str(decision["case_key"]),
            fact_at=fact_time(decision.get("as_of_at") or latest["proposal"]["as_of_at"]),
            basis={"final_decision": decision.get("final_decision") or {}},
            data=decision,
        )
        for decision in decisions
    ]

    def render(batch):
        return Rendered({"embeds": [embeds.candidate_embed(decision=batch[0].data)]})

    config = load_config()
    report = publish(
        TOPIC, notices, render,
        context=context or default_context(config),
        target=discord_target(TOPIC.channel_kind, config=config, override=target),
    )
    return report.delivered


__all__ = ["run"]
