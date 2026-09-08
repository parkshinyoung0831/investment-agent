"""경제 발표 결과를 v1 notifications outbox에 기록하고 디스패치한다."""
from __future__ import annotations

import argparse
from collections.abc import Sequence

from investment_agent.platform.logging import get_logger
from investment_agent.config import load_config
from investment_agent.notifications.econ_calendar import db as store
from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.econ_calendar import embeds
from investment_agent.notifications.outbox import Outbox
from investment_agent.notifications.service import NotificationService
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.platform.clock import utc_now
from investment_agent.reporting.notifications.connections import configured_database

log = get_logger(__name__)


def run(event_keys: list[str] | None = None, *, target: str | None = None) -> int:
    config = load_config()
    database = configured_database(config)
    outbox = Outbox(database)
    store.configure(outbox, database)
    rows = store.load_pending(event_keys)
    if not rows:
        log.info("econ release: no pending releases — silent skip")
        return 0
    target_id = discord_target("econ_calendar_release", config=config, override=target)
    service = NotificationService(outbox, DiscordChannel(config), clock=utc_now)
    for offset in range(0, len(rows), 5):
        batch = rows[offset:offset + 5]
        key = str(batch[0]["event_key"])
        service.enqueue(
            producer=store.PRODUCER,
            notification_key=store.notification_key(key),
            kind=store.KIND,
            target=target_id,
            entity_key=key,
            period_end=str(batch[0].get("ref_period") or "") or None,
            message={"content": "", "embeds": [embeds.build(batch)]},
        )
    results = service.run_pending()
    return sum(1 for result in results if result.status == "sent")


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="investment_agent.notifications.econ_calendar.run",
        description="경제 발표 결과를 outbox에 등록하고 디스패치한다.",
    ).parse_args(argv)
    return run()


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
