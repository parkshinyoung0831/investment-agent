"""로컬 운영 하네스의 OS 서비스 등록 계획을 만들고 선택적으로 적용한다."""
from __future__ import annotations

import argparse
import os
import sys

from investment_agent.platform.serialization import canonical_json
from investment_agent.operations.harness.service_install import (
    INSTALL_CONFIRMATION,
    apply_install_plan,
    macos_launchd_plan,
    windows_task_plan,
)

from investment_agent.operations.paths import REPOSITORY_ROOT as _ROOT
_APPROVAL_LABEL = "com.local.investment-ai-approval-listener"


def _require_apply_environment(*, service: str, mode: str) -> None:
    required: set[str] = set()
    if service in {"all", "harness"}:
        required.update({
            "SUPABASE_URL",
            "SUPABASE_SERVICE_KEY",
            "AI_INVESTOR_BASE_URL",
            "AI_INVESTOR_MODEL",
            "AI_INVESTOR_TRADINGAGENTS_PROVIDER",
        })
    if service in {"all", "approval-listener"} or mode == "approval_workflow":
        required.update({
            "SUPABASE_URL",
            "SUPABASE_SERVICE_KEY",
            "DISCORD_APPROVAL_BOT_TOKEN",
            "DISCORD_GUILD_ID",
            "DISCORD_CHANNEL_AI_APPROVALS",
        })
        if not (
            os.environ.get("DISCORD_APPROVER_USER_IDS", "").strip()
            or os.environ.get("DISCORD_APPROVER_USER_ID", "").strip()
        ):
            required.add("DISCORD_APPROVER_USER_IDS")
    if mode == "approval_workflow" and service in {"all", "harness"}:
        required.update({"TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET", "TOSS_ACCOUNT_SEQ"})
    missing = sorted(name for name in required if not os.environ.get(name, "").strip())
    if missing:
        raise RuntimeError(
            "service registration preflight is missing: " + ", ".join(missing)
        )


def _plans(*, platform: str, common: dict, service: str, mode: str):
    builder = windows_task_plan if platform == "windows" else macos_launchd_plan
    plans = []
    if service in {"all", "harness"}:
        plans.append(builder(
            **common,
            entry_arguments=("--serve", "--mode", mode),
        ))
    if service in {"all", "approval-listener"}:
        options = {
            **common,
            "label": _APPROVAL_LABEL,
            "entry_module": "investment_agent.operations.commands.approval_listener_service",
            "entry_arguments": ("--state-dir", common["state_dir"]),
        }
        if platform == "windows":
            options["descriptor_filename"] = "discord_approval_listener.task.xml"
        else:
            options["log_prefix"] = "discord_approval_listener"
        plans.append(builder(**options))
    return tuple(plans)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="투자 분석 하네스 로컬 서비스 등록")
    parser.add_argument("--platform", choices=("windows", "macos"), required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--repository-root", default=str(_ROOT))
    parser.add_argument(
        "--service",
        choices=("all", "harness", "approval-listener"),
        default="all",
    )
    parser.add_argument(
        "--mode",
        choices=("analysis_only", "approval_workflow"),
        default="analysis_only",
        help="하네스 서비스 모드. approval_workflow도 kill switch 기본값은 on이다.",
    )
    parser.add_argument(
        "--state-dir",
        default=str(_ROOT / "artifacts" / "ops" / "investment_harness"),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)

    common = {
        "python_executable": args.python,
        "repository_root": args.repository_root,
        "state_dir": args.state_dir,
    }
    plans = _plans(
        platform=args.platform,
        common=common,
        service=args.service,
        mode=args.mode,
    )
    if not args.apply:
        sys.stdout.write(canonical_json({
            "dry_run": True,
            "required_confirmation": INSTALL_CONFIRMATION,
            "plans": [plan.to_dict() for plan in plans],
        }) + "\n")
        return 0
    _require_apply_environment(service=args.service, mode=args.mode)
    for plan in plans:
        apply_install_plan(plan, apply=True, confirm=args.confirm)
    sys.stdout.write(canonical_json({
        "registered": True,
        "labels": [plan.label for plan in plans],
    }) + "\n")
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
