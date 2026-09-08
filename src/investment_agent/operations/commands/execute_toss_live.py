"""소비되지 않은 Discord live 승인 하나를 토스 실주문 worker에 넘긴다.

이 entry는 실제 돈을 움직일 수 있다. 단, ``TOSS_LIVE_ENABLED=true``, kill switch 해제,
서명된 Discord 승인, fresh 계좌 재검증이 모두 일치하지 않으면 POST 전에 종료한다.
"""
from __future__ import annotations

import argparse
import os

from investment_agent.platform.logging import get_logger
from investment_agent.execution.brokers.toss.orders import TossOrderApi
from investment_agent.execution.db import ExecutionRepository
from investment_agent.execution.approval.discord import DiscordApprovalClient
from investment_agent.execution.safety.control import LiveTradingControls
from investment_agent.execution.orders.live_worker import TossLiveExecutionWorker
from investment_agent.operations.harness.reporting import DiscordOpsAlert, HarnessReporter

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.execute_toss_live")
    parser.add_argument("--approval-id", required=True)
    args = parser.parse_args(argv)

    repository = ExecutionRepository()
    approval_id = args.approval_id
    reporter = HarnessReporter(logger=log, alerts=DiscordOpsAlert(log))

    from investment_agent.operations.harness.emergency import is_execution_locked_down
    if is_execution_locked_down():
        reporter.error("execution_locked_down", approval_id=approval_id)
        return 1

    try:
        # env·로컬 sentinel과 별개로 DB 운영자가 관리하는 fail-closed control도 통과해야 한다.
        repository.load_control_state().assert_live_manual_allowed()
        result = TossLiveExecutionWorker(
            repository=repository,
            api=TossOrderApi(),
            controls=LiveTradingControls.from_env(),
        ).execute(approval_id)
    except Exception as exc:  # worker가 원장에 상태를 먼저 남기며 여기서는 비밀 없는 타입만 알린다.
        reporter.error(
            "toss_live_execution_stopped",
            approval_id=approval_id,
            error_type=type(exc).__name__,
        )
        approval = repository.load_approval(approval_id)
        if approval and approval.discord_message_id:
            try:
                DiscordApprovalClient(
                    bot_token=os.environ["DISCORD_APPROVAL_BOT_TOKEN"],
                    guild_id=approval.discord_guild_id,
                ).set_status_text(
                    channel_id=approval.discord_channel_id,
                    message_id=approval.discord_message_id,
                    content=(
                        "⛔ 자동 주문을 중단했습니다. 주문 재전송은 하지 않았습니다. "
                        "운영 로그와 재조정 상태를 확인해 주세요."
                    ),
                )
            except Exception:
                reporter.error("discord_approval_status_update_failed", approval_id=approval_id)
        return 1
    reporter.event(
        "toss_live_orders_submitted",
        approval_id=result.approval_id,
        intent_id=result.intent_id,
        order_count=len(result.submitted),
        status=result.status,
    )
    approval = repository.load_approval(result.approval_id)
    if approval and approval.discord_message_id:
        try:
            DiscordApprovalClient(
                bot_token=os.environ["DISCORD_APPROVAL_BOT_TOKEN"],
                guild_id=approval.discord_guild_id,
            ).set_status_text(
                channel_id=approval.discord_channel_id,
                message_id=approval.discord_message_id,
                content=(
                    f"✅ 재검증을 통과해 주문 {len(result.submitted)}건을 접수했습니다. "
                    "현재 체결·부분체결 상태를 재조정하고 있습니다."
                ),
            )
        except Exception:
            reporter.error(
                "discord_approval_status_update_failed",
                approval_id=result.approval_id,
            )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
