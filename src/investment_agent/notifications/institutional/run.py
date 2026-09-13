"""거장 13F — 새 제출은 그 사람의 포럼 스레드에 한 번, 분기 요약은 한 장을 고쳐 가며 알린다."""
from __future__ import annotations

from investment_agent.config import load_config
from investment_agent.notifications.channels.discord import ForumThread
from investment_agent.notifications.channels.routing import guru_tag_ids, guru_thread_title
from investment_agent.notifications.engine import PublishContext, Rendered, default_context, publish
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.platform.logging import get_logger

from . import card, dataset, embeds
from .state import FILING_TOPIC, QUARTER_TOPIC, filing_notice, quarter_notice

log = get_logger(__name__)


def run(*, target: str | None = None, context: PublishContext | None = None) -> int:
    """최신 분기의 제출과 종합 요약을 원장에 맡긴다."""
    config = load_config()
    context = context or default_context(config)
    summary_id = discord_target(QUARTER_TOPIC.channel_kind, config=config, override=target)

    data = dataset.load_snapshot()
    period = card._latest_period(data)
    filings = card._latest_filings(data, period)
    if not filings:
        log.info("institutional: 최신 분기 제출 없음 period=%s", period)
        return 0

    forum = _forum(config)
    filing_target = forum or summary_id

    def render_filing(batch):
        notice, = batch
        ctx = card.build_filing(data, str(notice.data["name"]))
        return Rendered({"embeds": [embeds.build_filing(ctx)]}, thread=_thread(ctx, forum, config))

    delivered = publish(
        FILING_TOPIC, [filing_notice(filing, filing) for filing in filings], render_filing,
        context=context, target=filing_target,
    ).delivered

    def render_quarter(_batch):
        return Rendered({"embeds": [embeds.build_quarterly(card.build_quarterly(data))]})

    delivered += publish(
        QUARTER_TOPIC, [quarter_notice(period, filings)], render_quarter, context=context, target=summary_id,
    ).delivered
    log.info("institutional notifications finished period=%s delivered=%d", period, delivered)
    return delivered


def _forum(config) -> str | None:
    """거장 포럼이 없으면 요약 채널로 떨어뜨린다.

    fail-open이다 — 목적지를 못 찾았다고 카드를 버리면 그 분기의 공시가 통째로
    사라지고, 사라졌다는 사실도 남지 않는다. 요약 채널로라도 보내고 이유를 남긴다.
    """
    try:
        return discord_target(FILING_TOPIC.channel_kind, config=config)
    except Exception as exc:  # noqa: BLE001 - 목적지 미설정이 발송을 막지 않는다
        log.warning("guru forum is not configured; falling back to the summary channel",
                    extra={"error": repr(exc)})
        return None


def _thread(ctx: dict, forum: str | None, config) -> ForumThread | None:
    """사람마다 스레드 하나. 스레드의 정체성은 운용사 CIK다 — 표시 이름이 바뀌어도 갈라지지 않는다."""
    manager_cik = str(ctx.get("manager_cik") or "")
    name = str(ctx.get("name") or "")
    if forum is None or not manager_cik or not name:
        return None
    try:
        tags = tuple(guru_tag_ids(manager_cik, forum, config=config))
    except Exception as exc:  # noqa: BLE001 - 태그 실패가 발송을 막지 않는다
        log.warning("guru forum tag lookup failed; sending without a tag",
                    extra={"manager_cik": manager_cik, "error": repr(exc)})
        tags = ()
    return ForumThread(manager_cik, guru_thread_title(name), tags)


__all__ = ["run"]
