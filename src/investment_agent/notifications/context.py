"""운영 알림 원장과 채널 조립. 발행 엔진은 구체 구현을 알지 않는다."""
from __future__ import annotations

from typing import Any

from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.db import PostgresNotificationLedger
from investment_agent.notifications.engine import PublishContext, new_owner
from investment_agent.reporting.notifications.connections import configured_database


def default_context(config: Any) -> PublishContext:
    return PublishContext(
        PostgresNotificationLedger(configured_database(config)), DiscordChannel(config), new_owner(),
    )
