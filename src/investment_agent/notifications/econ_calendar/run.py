"""경제 발표의 first actual을 알린다. 발표 하나 = 알림 하나, 전송은 최대 5건씩 묶는다."""
from __future__ import annotations

import argparse
from collections.abc import Sequence

from investment_agent.config import load_config
from investment_agent.notifications.econ_calendar import db as store
from investment_agent.notifications.econ_calendar import embeds
from investment_agent.notifications.engine import (
    Notice,
    PublishContext,
    Rendered,
    default_context,
    publish,
)
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.notifications.topics import topic
from investment_agent.platform.logging import get_logger
from investment_agent.reporting.notifications.connections import configured_database
from investment_agent.reporting.services.economic_releases import parse_event_key

log = get_logger(__name__)

TOPIC = topic("econ.release")


def notices(rows: Sequence[dict]) -> list[Notice]:
    """발표의 정체성은 (지표, 기준 기간)이다. 알린 뒤의 개정은 이 알림을 다시 건드리지 않는다."""
    out = []
    for row in rows:
        parsed = parse_event_key(row.get("event_key"))
        if parsed is None:
            raise ValueError("invalid economic release event key")
        series_id, ref_period = parsed
        out.append(Notice(
            subject=series_id,
            occurrence=ref_period,
            fact_at=store.parse_time(row["first_actual_at"]),
            basis={"first_actual_value": row.get("first_actual_value"), "unit": row.get("unit")},
            data=row,
        ))
    return out


def render(batch: list[Notice]) -> Rendered:
    return Rendered({"content": "", "embeds": [embeds.build([notice.data for notice in batch])]})


def run(event_keys: list[str] | None = None, *, target: str | None = None,
        context: PublishContext | None = None) -> int:
    config = load_config()
    rows = store.load_released(configured_database(config), event_keys)
    if not rows:
        log.info("econ release: no released first actual in the lookback window")
        return 0
    report = publish(
        TOPIC, notices(rows), render,
        context=context or default_context(config),
        target=discord_target(TOPIC.channel_kind, config=config, override=target),
    )
    return report.delivered


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="investment_agent.notifications.econ_calendar.run",
        description="경제 발표 결과를 원장에 맡겨 한 번만 알린다.",
    ).parse_args(argv)
    run()
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
