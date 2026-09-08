"""Discord 서명 버튼을 승인 원장에만 기록하는 상시 listener.

    python -m investment_agent.operations.commands.approval_listener
"""
from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from investment_agent.execution.approval.ledger import ApprovalSigner, approver_allowlist
from investment_agent.execution.approval.secret import load_or_create_approval_secret
from investment_agent.execution.approval.service import ApprovalWorkflow
from investment_agent.execution.db import ExecutionRepository
from investment_agent.execution.approval.discord import DiscordApprovalClient, run_gateway_listener


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """승인 전용 bot을 실행한다. 어떤 broker client도 만들지 않는다."""

    argparse.ArgumentParser(
        prog="investment_agent.operations.commands.approval_listener",
        description="Discord 승인 버튼 listener를 실행한다.",
    ).parse_args(argv)
    token = _required("DISCORD_APPROVAL_BOT_TOKEN")
    approvers = approver_allowlist(os.environ.get("DISCORD_APPROVER_USER_IDS", ""))
    workflow = ApprovalWorkflow(
        repository=ExecutionRepository(),
        signer=ApprovalSigner(load_or_create_approval_secret()),
        discord_client=DiscordApprovalClient(
            bot_token=token,
            guild_id=_required("DISCORD_GUILD_ID"),
        ),
        runtime_approver_user_ids=approvers,
    )
    run_gateway_listener(bot_token=token, handler=workflow)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
