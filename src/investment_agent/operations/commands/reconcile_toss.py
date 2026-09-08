"""토스 REST를 단일 기준으로 로컬 주문·부분체결 상태를 재동기화한다."""
from __future__ import annotations

import argparse
import os

from investment_agent.platform.logging import get_logger
from investment_agent.execution.approval.status import publish_reconciliation_statuses
from investment_agent.execution.brokers.toss import client as toss
from investment_agent.execution.brokers.toss.orders import TossOrderApi
from investment_agent.execution.db import ExecutionRepository
from investment_agent.execution.reconciliation.worker import TossReconciliationWorker
from investment_agent.operations.harness.reporting import DiscordOpsAlert, HarnessReporter

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.reconcile_toss")
    parser.add_argument("--account-seq", type=int)
    args = parser.parse_args(argv)
    reporter = HarnessReporter(logger=log, alerts=DiscordOpsAlert(log))
    account_seq = toss.resolve_account_seq(args.account_seq)
    repository = ExecutionRepository()
    try:
        result = TossReconciliationWorker(
            repository=repository,
            api=TossOrderApi(),
            account_seq=account_seq,
            alert=lambda event, details: reporter.error(event, **details),
        ).run_once()
    except Exception as exc:
        reporter.error("toss_reconciliation_failed", error_type=type(exc).__name__)
        return 1
    reporter.event(
        "toss_reconciliation_completed",
        inspected=result.inspected,
        updated=result.updated,
        unresolved=len(result.unresolved_unknown),
        external_open_orders=len(result.external_open_order_ids),
    )
    published = publish_reconciliation_statuses(
        repository=repository,
        updates=result.card_updates,
        account_seq=account_seq,
        bot_token=os.environ.get("DISCORD_APPROVAL_BOT_TOKEN"),
        expected_guild_id=os.environ.get("DISCORD_GUILD_ID"),
        expected_channel_id=os.environ.get("DISCORD_CHANNEL_AI_APPROVALS"),
    )
    if published.failed:
        reporter.error(
            "discord_reconciliation_status_update_failed",
            failed=published.failed,
        )
    elif published.sent:
        reporter.event(
            "discord_reconciliation_status_updated",
            sent=published.sent,
        )
    return 1 if result.unresolved_unknown or result.external_open_order_ids else 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
