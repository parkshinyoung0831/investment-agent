"""월간 전략 알림 — 적용월마다 종합 요약 한 장과 전략별 배분 카드 한 장씩을 원장에 맡긴다."""
from __future__ import annotations

from collections import defaultdict

from investment_agent.config import load_config
from investment_agent.notifications.channels import routing
from investment_agent.notifications.channels.discord import ForumThread
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

from .db import load_prev_alloc, load_recent_allocations
from .embeds import build_card, build_summary
from .models import AllocationRow, StrategyNotification

log = get_logger(__name__)

ALLOCATION_TOPIC = topic("strategy.allocation")
MONTH_TOPIC = topic("strategy.month")
ALL_STRATEGIES = "all"


def _strategy_tags(target: str, strategy_id: str) -> tuple[str, ...]:
    """전략 태그를 이름에서 snowflake로 바꾼다. 못 찾으면 태그 없이 보낸다."""
    name = routing.STRATEGY_TAGS_MAP.get(strategy_id)
    if not name:
        return ()
    try:
        from investment_agent.notifications.channels.directory import guild_directory

        directory = guild_directory(load_config())
    except Exception:  # noqa: BLE001 - 태그 실패가 발송을 막지 않는다
        log.warning("discord 길드 조회 실패 — 전략 태그 없이 보낸다")
        return ()
    return tuple(directory.tag_ids_by_channel_id(target, (name,)))


def _card(raw: dict) -> tuple[StrategyNotification, dict]:
    row = AllocationRow.from_mapping(raw)
    return build_card(row, load_prev_alloc(row.strategy_id, row.apply_date)), row.alloc


def allocation_notices(rows: list[dict]) -> list[Notice]:
    """전략 배분의 정체성은 (전략, 적용월)이다."""
    return [
        Notice(
            subject=str(row["strategy_id"]),
            occurrence=str(row["apply_date"])[:10],
            fact_at=fact_time(str(row["apply_date"])[:10]),
            basis={"weights": {str(k): float(v) for k, v in (row.get("weights") or {}).items()}},
            data=row,
        )
        for row in rows
    ]


def month_notices(rows: list[dict]) -> list[Notice]:
    """적용월마다 종합 요약 한 장."""
    by_month: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_month[str(row["apply_date"])[:10]].append(row)
    return [
        Notice(
            subject=ALL_STRATEGIES,
            occurrence=month,
            fact_at=fact_time(month),
            basis={"strategies": sorted(str(row["strategy_id"]) for row in month_rows)},
            data=month_rows,
        )
        for month, month_rows in sorted(by_month.items())
    ]


def run(*, summary_target: str | None = None, target: str | None = None,
        context: PublishContext | None = None) -> int:
    config = load_config()
    rows = load_recent_allocations()
    if not rows:
        log.info("no recent strategy allocations")
        return 0
    context = context or default_context(config)
    summary_id = discord_target(MONTH_TOPIC.channel_kind, config=config, override=summary_target)
    forum_id = discord_target(ALLOCATION_TOPIC.channel_kind, config=config, override=target)

    def render_month(batch):
        notice, = batch
        cards, allocations = [], {}
        for raw in notice.data:
            card, alloc = _card(raw)
            cards.append(card)
            allocations[str(raw["strategy_id"])] = alloc
        summary = build_summary(cards, allocations)
        if not summary:
            raise ValueError("strategy summary has nothing to show")
        return Rendered({"embeds": [summary]})

    def render_allocation(batch):
        notice, = batch
        card, _alloc = _card(notice.data)
        # 아카이브는 포럼이다 — 전략마다 스레드 하나에 월간 배분이 쌓인다.
        return Rendered(
            {"embeds": [card.embed]},
            thread=ForumThread(notice.subject, routing.strategy_thread_title(notice.subject),
                               _strategy_tags(forum_id, notice.subject)),
        )

    delivered = publish(MONTH_TOPIC, month_notices(rows), render_month, context=context, target=summary_id).delivered
    delivered += publish(
        ALLOCATION_TOPIC, allocation_notices(rows), render_allocation, context=context, target=forum_id,
    ).delivered
    return delivered


__all__ = ["ALLOCATION_TOPIC", "MONTH_TOPIC", "allocation_notices", "month_notices", "run"]
