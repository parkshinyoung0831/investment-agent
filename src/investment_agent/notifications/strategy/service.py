"""Strategy notification orchestration through the v1 notification outbox."""
from __future__ import annotations

import time
from collections.abc import Sequence

from investment_agent.config import load_config
from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.outbox import Outbox
from investment_agent.notifications.channels import routing
from investment_agent.notifications.service import NotificationService
from investment_agent.notifications.subscriptions import discord_targets
from investment_agent.platform.clock import utc_now
from investment_agent.platform.logging import get_logger
from investment_agent.reporting.notifications.connections import configured_database

from .db import load_pending, load_prev_alloc, mark_sent
from .embeds import build_card, build_summary
from .models import AllocationRow, StrategyNotification

log = get_logger(__name__)
_BATCH_GAP_S = 1.5


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


def _build_cards(rows: list[dict]) -> tuple[list[StrategyNotification], dict[str, dict]]:
    """개별 카드와 종합 카드에 사용할 전략별 배분을 계산한다."""
    cards: list[StrategyNotification] = []
    allocations: dict[str, dict] = {}
    for raw in rows:
        row = AllocationRow.from_mapping(raw)
        prev = load_prev_alloc(row.strategy_id, row.apply_date)
        cards.append(build_card(row, prev))
        allocations[row.strategy_id] = row.alloc
    return cards, allocations


def _service() -> tuple[NotificationService, object]:
    config = load_config()
    database = configured_database(config)
    return NotificationService(Outbox(database), DiscordChannel(config), clock=utc_now), config


def _enqueue_batch(
    rows: list[dict], cards: list[StrategyNotification], allocations: dict[str, dict],
    *, service: NotificationService, summary_target: str, target: str,
) -> int:
    """한 배치의 outbox 행을 등록하고 성공한 allocation만 완료 표시한다."""
    apply_date = str(rows[0]["apply_date"])
    keys: set[str] = set()
    summary = build_summary(cards, allocations)
    if summary:
        key = f"summary:{apply_date}"
        result = service.enqueue(
            producer="strategy", notification_key=key, kind="strategy_summary",
            target=summary_target, message={"embeds": [summary]}, period_end=apply_date,
        )
        if result.status != "error":
            keys.add(key)

    for card in cards:
        strategy_id, card_date = card.allocation_id.split(":", 1)
        key = f"allocation:{strategy_id}:{card_date}"
        result = service.enqueue(
            producer="strategy", notification_key=key, kind="strategy",
            target=target, message={"embeds": [card.embed]},
            entity_key=strategy_id, period_end=card_date,
            # 아카이브는 포럼이다 — 전략마다 스레드 하나에 월간 배분이 쌓인다.
            thread_name=routing.strategy_thread_title(strategy_id),
            thread_tags=_strategy_tags(target, strategy_id),
        )
        if result.status != "error":
            keys.add(key)

    sent_keys = {
        result.notification_key
        for result in service.run_pending()
        if result.producer == "strategy" and result.status == "sent"
    }
    for card in cards:
        strategy_id, card_date = card.allocation_id.split(":", 1)
        if f"allocation:{strategy_id}:{card_date}" in sent_keys:
            mark_sent(card.allocation_id, strategy_id=strategy_id, apply_date=card_date)
    return sum(key in sent_keys for key in keys)


def run(*, service: NotificationService | None = None,
        summary_targets: Sequence[str] | None = None,
        targets: Sequence[str] | None = None) -> int:
    """대기 중인 전략 배분을 outbox에 등록하고 전송한다."""
    if service is None:
        service, config = _service()
    else:
        config = load_config()
    summary_ids = tuple(summary_targets) if summary_targets is not None else discord_targets(
        "strategy_summary", config=config
    )
    target_ids = tuple(targets) if targets is not None else discord_targets(
        "strategy", config=config
    )
    if len(summary_ids) != 1 or len(target_ids) != 1:
        raise RuntimeError("strategy notifications require one summary and one allocation target")
    total_batches = 0
    total_sent = 0
    # 전송 실패·중복은 로컬 완료 시각을 바꾸지 않는다. 한 snapshot만 순회해야
    # 같은 배치를 무한 재조회하지 않고 outbox의 재시도·불명 상태를 보존한다.
    pending = sorted(load_pending(), key=lambda row: str(row["apply_date"]))
    batches: dict[str, list[dict]] = {}
    for row in pending:
        batches.setdefault(str(row["apply_date"]), []).append(row)
    for rows in batches.values():
        if total_batches:
            time.sleep(_BATCH_GAP_S)
        total_batches += 1
        cards, allocations = _build_cards(rows)
        sent = _enqueue_batch(
            rows, cards, allocations, service=service,
            summary_target=summary_ids[0], target=target_ids[0],
        )
        total_sent += sent
        log.info("strategy notification batch finished apply_date=%s sent=%d", rows[0]["apply_date"], sent)
    if not total_batches:
        log.info("no pending strategy allocations")
    return total_sent
