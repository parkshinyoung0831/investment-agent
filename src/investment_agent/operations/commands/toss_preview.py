"""토스 실계좌를 읽되 주문 API를 호출하지 않는 수동 주문표 진입점."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from investment_agent.platform.storage_paths import repository_artifact_root
from investment_agent.platform.logging import get_logger
from investment_agent.execution.brokers.toss import client as toss
from investment_agent.execution.db import ExecutionRepository
from investment_agent.execution.orders.planning import whole_share_planner
from investment_agent.execution.safety.control import planning_notionals
from investment_agent.execution.orders.toss_manual import export_handoff, prepare_handoff

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.toss_preview")
    parser.add_argument("--intent-id", required=True)
    parser.add_argument("--account-seq", type=int)
    parser.add_argument(
        "--export",
        action="store_true",
        help="주문하지 않고 사람이 검토할 CSV와 manifest만 저장",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="내보낼 때 intent-id를 그대로 한 번 더 입력",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repository_artifact_root() / "execution" / "toss",
    )
    args = parser.parse_args(argv)

    repository = ExecutionRepository()
    intent = repository.load_intent(args.intent_id)
    if intent is None:
        raise RuntimeError("execution intent not found")
    account_seq = toss.resolve_account_seq(args.account_seq)
    planner = whole_share_planner(planning_notionals(os.environ), quantity_decimals=6)
    handoff = prepare_handoff(
        intent,
        account_seq=account_seq,
        eligible_buy_symbols=repository.current_tracked_tickers(),
        planner=planner,
        required_mode="paper",
    )
    log.info(
        "NON_EXECUTABLE Toss preview intent_id=%s orders=%d hash=%s",
        handoff.intent_id,
        len(handoff.tickets),
        handoff.manifest_hash,
    )
    for ticket in handoff.tickets:
        log.info(
            "preview %s %s quantity=%s reference_price=%s notional=%s",
            ticket.side,
            ticket.symbol,
            ticket.order_quantity,
            ticket.reference_price,
            ticket.estimated_notional,
        )
    if args.export:
        csv_path, manifest_path = export_handoff(
            handoff,
            output_dir=args.output_dir,
            confirm=args.confirm,
        )
        log.info("manual review files exported csv=%s manifest=%s", csv_path, manifest_path)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
