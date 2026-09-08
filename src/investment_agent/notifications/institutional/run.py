"""13F institutional notifications registered and dispatched through v1 outbox."""
from __future__ import annotations

import os

from investment_agent.config import load_config
from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.channels.routing import guru_tag_ids, guru_thread_title
from investment_agent.notifications.outbox import Outbox
from investment_agent.notifications.service import NotificationService
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.platform.clock import utc_now
from investment_agent.platform.logging import get_logger
from investment_agent.reporting.notifications.institutional import db
from investment_agent.reporting.notifications.connections import configured_database

from . import card, dataset, embeds
from .state import filing_key, quarterly_key

log = get_logger(__name__)


def run(*, service: NotificationService | None = None,
        target: str | None = None) -> int:
    """최신 분기의 신규 제출과 종합 카드를 outbox에 등록하고 전송한다."""
    config = load_config()
    database = configured_database(config)
    summary_id = discord_target("institutional", config=config, override=target)
    if service is None:
        service = NotificationService(
            Outbox(database), DiscordChannel(config), clock=utc_now,
        )

    data = dataset.load_snapshot()
    period = card._latest_period(data)
    filings = card._latest_filings(data, period)
    sent_keys = db.sent_keys()
    force = os.environ.get("GURUS_NOTIFY_FORCE", "").lower() in {"1", "true", "on"}
    new_filings = [
        filing for filing in filings
        if force or filing_key(str(filing["accession_no"])) not in sent_keys
    ]

    keys: set[str] = set()
    for filing in new_filings:
        ctx = card.build_filing(data, str(filing["name"]))
        key = filing_key(str(ctx["accession_no"]))
        target, thread_name, thread_tags = _filing_destination(
            ctx, summary_target=summary_id, config=config)
        result = service.enqueue(
            producer="institutional", notification_key=key, kind="filing",
            target=target,
            message={"embeds": [embeds.build_filing(ctx)]},
            entity_key=str(ctx["accession_no"]), period_end=period,
            thread_name=thread_name, thread_tags=thread_tags,
        )
        if result.status != "error":
            keys.add(key)

    summary_key = quarterly_key(period, len(filings))
    if new_filings or force or summary_key not in sent_keys:
        quarterly = card.build_quarterly(data)
        result = service.enqueue(
            producer="institutional", notification_key=summary_key, kind="quarterly",
            target=summary_id, message={"embeds": [embeds.build_quarterly(quarterly)]},
            entity_key=f"period:{period}", period_end=period,
        )
        if result.status != "error":
            keys.add(summary_key)

    results = service.run_pending()
    sent = sum(
        1 for result in results
        if result.producer == "institutional"
        and result.notification_key in keys
        and result.status == "sent"
    )
    log.info("institutional notifications finished period=%s sent=%d", period, sent)
    return sent


def _filing_destination(
    ctx: dict, *, summary_target: str, config,
) -> tuple[str, str | None, tuple[str, ...]]:
    """거장 포럼의 그 사람 스레드로 보낸다. 목적지가 없으면 요약 채널로 떨어뜨린다.

    fail-open이다 — 목적지를 못 찾았다고 카드를 버리면 그 분기의 공시가 통째로
    사라지고, 사라졌다는 사실도 남지 않는다. 요약 채널로라도 보내고 이유를 남긴다.
    """
    manager_cik = str(ctx.get("manager_cik") or "")
    name = str(ctx.get("name") or "")
    if not manager_cik or not name:
        return summary_target, None, ()
    try:
        target = discord_target("gurus_forum", config=config)
    except Exception as exc:  # noqa: BLE001 - 목적지 미설정이 발송을 막지 않는다
        log.warning(
            "guru forum is not configured; falling back to the summary channel",
            extra={"manager_cik": manager_cik, "error": repr(exc)},
        )
        return summary_target, None, ()
    try:
        tags = guru_tag_ids(manager_cik, target, config=config)
    except Exception as exc:  # noqa: BLE001 - 태그 실패가 발송을 막지 않는다
        log.warning(
            "guru forum tag lookup failed; sending without a tag",
            extra={"manager_cik": manager_cik, "error": repr(exc)},
        )
        tags = ()
    return target, guru_thread_title(name), tags
