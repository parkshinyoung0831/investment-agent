"""Gurus 13F backfill entrypoint."""
from __future__ import annotations

import argparse

from investment_agent.config import load_config
from investment_agent.operations.backfill import add_backfill_from_arg
from investment_agent.data.institutional import HISTORICAL_START_DATE
from investment_agent.data.institutional import persistence
from investment_agent.platform.db.postgres import Database


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.data.institutional.commands.institutional_backfill")
    add_backfill_from_arg(parser)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    backfill_from = args.backfill_from or HISTORICAL_START_DATE

    persistence.configure(Database.from_config(load_config()))

    from investment_agent.data.institutional.application import etl
    from investment_agent.data.universe.infrastructure.sources import sec

    metrics = etl.run(backfill_from, sec_client=sec)
    if metrics["failures"]:
        return 1
    mapping = etl.refresh_mappings(force=True)
    if mapping.get("mapping_provider_failed", 0):
        return 1
    # 백필의 목적은 이력 복원이지 과거 Discord 재발송이 아니다. 알림 원장은 topic
    # baseline보다 먼저 접수된 제출을 보내지 않으므로 여기서 따로 막을 것이 없다.
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
