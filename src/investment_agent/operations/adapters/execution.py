"""Execution-owner harness stage adapters."""
from __future__ import annotations

import os

from investment_agent.operations.adapters._metadata import _ID_PATTERNS, metadata_id
from investment_agent.operations.harness.commands import PythonModuleCommand
from investment_agent.operations.harness.contracts import StageContext, StageOutcome
from investment_agent.platform.serialization import parse_datetime

# 승인 카드를 보내는 데 필요한 설정. 카드 봇과 분리된 승인 봇, 승인할 수 있는 사람.
APPROVAL_SETTINGS = ("DISCORD_APPROVAL_BOT_TOKEN", "DISCORD_APPROVER_USER_IDS")


class ExecutionAdapters:
    def execution_intent(self, context: StageContext) -> StageOutcome:
        follow = context.completed_metadata.get("follow", {})
        if follow.get("status") != "planned":
            return StageOutcome.skipped({"reason": "no_follow_plan"})
        risk_id = metadata_id(
            context, stage_id="follow", key="risk_decision_id",
        )
        constructed_at = parse_datetime(str(follow.get("constructed_at") or ""))
        age = (self.now() - constructed_at).total_seconds()
        if age < 0 or age > 240:
            raise RuntimeError("portfolio snapshot expired before intent creation")
        intent = self.create_execution_intent(
            risk_decision_id=risk_id,
            execution_mode="live",
            confirmation=risk_id,
            ttl_minutes=self.approval_ttl_minutes,
            # retry·재시작에도 같은 intent ID가 나오도록 포트폴리오 완료 시각을 고정한다.
            now=constructed_at,
            repository=self.decision_repository,
            execution_repository=self.approval_repository,
        )
        intent_id = str(intent.intent_id)
        if _ID_PATTERNS["intent_id"].fullmatch(intent_id) is None:
            raise RuntimeError("intent creation returned an invalid ID")
        return StageOutcome.succeeded({
            "intent_id": intent_id,
            "expires_at": str(intent.expires_at),
        })
    def approval_request(self, context: StageContext) -> StageOutcome:
        intent_id = metadata_id(
            context,
            stage_id="execution_intent",
            key="intent_id",
            required=False,
        )
        if intent_id is None:
            return StageOutcome.skipped({"reason": "no_live_intent"})
        missing = [name for name in APPROVAL_SETTINGS if not os.environ.get(name, "").strip()]
        if missing:
            # 승인 요청은 매번 가지만, 승인 봇·승인자가 없으면 카드를 보낼 곳이 없다. 설정 전까지 실패로 쌓지 않는다.
            return StageOutcome.skipped({"reason": "approval_bot_not_configured", "missing": missing,
                                         "intent_id": intent_id})
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.operations.commands.request_toss_approval",
                ("--intent-id", intent_id),
                self.timeouts.get("approval_request", 180),
            ),
            stop_event=context.stop_event,
        )
        approval = self.approval_repository.approval_for_intent(intent_id)
        if approval is None:
            raise RuntimeError("approval request was not durably stored")
        approval_id = str(approval.approval_id)
        if _ID_PATTERNS["approval_id"].fullmatch(approval_id) is None:
            raise RuntimeError("approval request returned an invalid ID")
        if not approval.discord_message_id:
            raise RuntimeError("approval request has no bound Discord message")
        return StageOutcome.succeeded({
            "approval_id": approval_id,
            "intent_id": intent_id,
            "expires_at": str(approval.expires_at),
        })
    def approval_worker(self, context: StageContext) -> StageOutcome:
        intent_id = metadata_id(
            context,
            stage_id="approval_request",
            key="intent_id",
            required=False,
        )
        if intent_id is None:
            return StageOutcome.skipped({"reason": "no_approval_requested"})
        approval = self.approval_repository.approval_for_intent(intent_id)
        if approval is None or not approval.discord_message_id:
            raise RuntimeError("approval state is missing or not message-bound")
        approval_id = str(approval.approval_id)
        if _ID_PATTERNS["approval_id"].fullmatch(approval_id) is None:
            raise RuntimeError("approval state has an invalid ID")
        status = str(approval.status)
        now = self.now()
        if status == "pending":
            expires_at = parse_datetime(str(approval.expires_at))
            if now >= expires_at:
                return StageOutcome.skipped({
                    "approval_id": approval_id,
                    "reason": "approval_expired",
                })
            delay = min(
                self.approval_poll_seconds,
                max(1.0, (expires_at - now).total_seconds()),
            )
            return StageOutcome.waiting(
                resume_after_seconds=delay,
                metadata={"approval_id": approval_id, "status": status},
            )
        if status in {"rejected", "expired"}:
            return StageOutcome.skipped({
                "approval_id": approval_id,
                "reason": f"approval_{status}",
            })
        if status == "consumed":
            return StageOutcome.succeeded({
                "approval_id": approval_id,
                "execution": "already_consumed",
            })
        if status != "approved":
            raise RuntimeError("approval state is not executable")

        # 장 시작 전·주기 snapshot job과 별개로, 승인 소비 직전에도 최신값을 남긴다.
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.operations.commands.capture_toss_risk_snapshot",
                (),
                self.timeouts.get("risk_snapshot", 180),
            ),
            stop_event=context.stop_event,
        )
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.operations.commands.execute_toss_live",
                ("--approval-id", approval_id),
                self.timeouts.get("approval_worker", 10 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({
            "approval_id": approval_id,
            "execution": "submitted_for_reconciliation",
        })
    def risk_snapshot(self, context: StageContext) -> StageOutcome:
        if not self.risk_window.is_open(context.now):
            return StageOutcome.waiting(
                resume_after_seconds=self.risk_window.seconds_until_open(context.now),
                metadata={"reason": "outside_ny_risk_window"},
            )
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.operations.commands.capture_toss_risk_snapshot",
                (),
                self.timeouts.get("risk_snapshot", 180),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"captured_at": self.now().isoformat()})
    def reconcile(self, context: StageContext) -> StageOutcome:
        if not self.risk_window.is_open(context.now):
            return StageOutcome.waiting(
                resume_after_seconds=self.risk_window.seconds_until_open(context.now),
                metadata={"reason": "outside_ny_risk_window"},
            )
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.operations.commands.reconcile_toss",
                (),
                self.timeouts.get("reconcile", 180),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"reconciled_at": self.now().isoformat()})
