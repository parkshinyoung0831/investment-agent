"""S&P 500 경량 변경 감지와 tracked gate 갱신 진입점."""
from __future__ import annotations

import argparse
import time

from investment_agent.operations.runtime import elapsed_sec
from investment_agent.platform.logging import get_logger
from investment_agent.operations.monitoring.github import write_changed_output

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.data.universe.commands.universe_membership")
    parser.parse_args(argv)

    from investment_agent.data.universe.application import collection as etl
    from investment_agent.data.universe.infrastructure.sources import sec

    started = time.monotonic()
    etl.sync_exchange_listings(sec_get_json=sec.get_json)
    result = etl.reconcile_membership(audit_history=False)
    changed = bool(result["changed"])
    if changed:
        etl.sync_sec_entities(tracked_only=True, sec_get_json=sec.get_json)
    write_changed_output(changed)
    log.info(
        "universe membership check done: changed=%s added=%s removed=%s duration_sec=%.1f",
        changed,
        result["added"],
        result["removed"],
        elapsed_sec(started),
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
