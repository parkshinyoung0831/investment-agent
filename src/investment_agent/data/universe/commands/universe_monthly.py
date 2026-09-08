"""월간 Universe 정합성 진입점."""
from __future__ import annotations

import argparse
import time

from investment_agent.operations.runtime import elapsed_sec
from investment_agent.platform.logging import get_logger
from investment_agent.operations.monitoring.github import write_changed_output

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.data.universe.commands.universe_monthly")
    parser.parse_args(argv)

    from investment_agent.data.universe.application import collection as etl
    from investment_agent.data.universe.infrastructure.sources import sec

    t0 = time.monotonic()
    etl.sync_exchange_listings(sec_get_json=sec.get_json)
    etl.sync_sec_entities(sec_get_json=sec.get_json)
    membership = etl.reconcile_membership(audit_history=True)
    write_changed_output(bool(membership["changed"]))
    log.info(
        "universe monthly done: changed=%s duration_sec=%.1f",
        membership["changed"],
        elapsed_sec(t0),
    )
    return 0

if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
