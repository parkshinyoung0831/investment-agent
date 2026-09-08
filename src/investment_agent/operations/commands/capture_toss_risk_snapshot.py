"""실주문 없이 토스 USD sleeve 위험 기준선만 private DB에 기록한다."""
from __future__ import annotations

import argparse

from investment_agent.platform.logging import get_logger
from investment_agent.execution.brokers.toss.client import resolve_account_seq
from investment_agent.execution.db import ExecutionRepository
from investment_agent.execution.orders.risk_snapshot import capture_and_store_risk_snapshot

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="investment_agent.operations.commands.capture_toss_risk_snapshot"
    )
    parser.add_argument("--account-seq", type=int)
    args = parser.parse_args(argv)
    account_seq = resolve_account_seq(args.account_seq)
    result = capture_and_store_risk_snapshot(
        account_seq=account_seq,
        repository=ExecutionRepository(),
    )
    log.info(
        "Toss risk snapshot stored snapshot_id=%s positions=%d open_orders=%d captured_at=%s",
        result.snapshot_id,
        result.position_count,
        result.open_order_count,
        result.captured_at,
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
