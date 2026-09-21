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
from investment_agent.execution.safety.lockdown import set_execution_lockdown
from investment_agent.operations.harness.reporting import DiscordOpsAlert, HarnessReporter

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.reconcile_toss")
    parser.add_argument("--account-seq", type=int)
    args = parser.parse_args(argv)
    reporter = HarnessReporter(logger=log, alerts=DiscordOpsAlert(log))
    account_seq = toss.resolve_account_seq(args.account_seq)
    repository = ExecutionRepository()

    def broker_positions() -> dict[str, float]:
        from investment_agent.execution.orders.toss_manual import _us_holdings
        return _us_holdings(toss.fetch_holdings(account_seq))

    def lock_down(event: str, details: dict) -> None:
        # 신규 주문만 막는다. 이미 접수된 주문의 대사는 lockdown과 무관하게 계속된다.
        set_execution_lockdown(reason=event, details={**details, "source": "reconcile_toss"})
        reporter.error("execution_lockdown_set", reason=event)

    try:
        result = TossReconciliationWorker(
            repository=repository,
            api=TossOrderApi(),
            account_seq=account_seq,
            alert=lambda event, details: reporter.error(event, **details),
            positions_provider=broker_positions,
            baseline_store=repository,
            on_breach=lock_down,
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
        position_check=result.position_check,
        position_mismatches=len(result.position_mismatches),
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
    # 종료 코드는 "재실행하면 달라지는가"를 뜻한다. 아래 셋은 **사람이 확인할 사실**이고
    # 재실행으로 사라지지 않는다 — 토스 앱에서 직접 낸 미체결 주문 하나가 있으면
    # `external_open_order_ids`가 계속 비지 않아 이 job이 60초마다 영구 실패했고,
    # 실패마다 운영 채널로 경보가 나가 진짜 대사 장애와 구분되지 않았다(감사 OP2-19).
    # 실행 실패는 위쪽 `except`가 이미 1로 처리한다. 발견 사항은 조용해지지 않도록
    # `reporter.error`로 한 번 올리고 종료 코드는 0으로 둔다.
    findings = {
        "unresolved_unknown": list(result.unresolved_unknown),
        "external_open_orders": list(result.external_open_order_ids),
        "position_mismatches": [mismatch.ticker for mismatch in result.position_mismatches],
    }
    if any(findings.values()):
        reporter.error("toss_reconciliation_needs_operator_review", **findings)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
