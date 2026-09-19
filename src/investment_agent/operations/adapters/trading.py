"""Trading-owner harness stage adapters."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from investment_agent.operations.adapters._metadata import _ID_PATTERNS, metadata_id
from investment_agent.operations.harness.commands import PythonModuleCommand
from investment_agent.operations.harness.contracts import StageContext, StageOutcome


def follow_system_target(*, target_id: str, store: Any, repository: Any, now: datetime) -> Any:
    """System 목표 하나를 새 Toss 계좌 스냅샷과 비교해 추종 제안을 기록한다."""
    from investment_agent.execution.brokers.toss.client import resolve_account_seq
    from investment_agent.execution.orders.toss_snapshot import capture_toss_account_snapshot
    from investment_agent.trading.my_portfolio import plan_follow

    target = store.latest_target(approved_only=True)
    if target is None or target.target_id != target_id:
        raise RuntimeError("the selected System target is no longer the latest approved target")
    if not repository.has_approved_promotion(target.model_artifact_id, "live"):
        raise RuntimeError("System target model artifact has not been manually promoted to live")
    snapshot = capture_toss_account_snapshot(account_seq=resolve_account_seq(None))
    return plan_follow(repository, target=target, snapshot=snapshot, now=now)


class TradingAdapters:
    def analysis(self, context: StageContext) -> StageOutcome:
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.trading.decision.analysis",
                (
                    "--as-of", context.now.isoformat(), "--limit", str(self.analysis_limit),
                    # timeout에 걸려 강제 종료되면 끝낸 종목의 신호까지 잃는다. 여유를 두고 스스로 멈추게 한다.
                    "--max-runtime-seconds", str(int(self.timeouts.get("analysis", 2 * 60 * 60) * 0.85)),
                ),
                self.timeouts.get("analysis", 2 * 60 * 60),
            ),
            stop_event=context.stop_event,
        )
        try:
            batch_id = self.decision_repository.signal_batch_id_for_as_of(
                as_of_at=context.now,
            )
        except LookupError:
            # 오늘 모델 예산이 없어 분석이 시작되지 않은 회차다. 실패로 적으면 상태창이 매 30분 실패로 뒤덮인다.
            # 분석이 돌다 실패하면 명령이 0이 아닌 코드로 끝나 위에서 이미 예외가 난다.
            return StageOutcome.skipped({"reason": "no_signal_batch", "decision_as_of_at": context.now.isoformat()})
        if batch_id is None or _ID_PATTERNS["batch_id"].fullmatch(batch_id) is None:
            raise RuntimeError("analysis completed without a valid signal batch")
        return StageOutcome.succeeded({
            "batch_id": batch_id,
            "decision_as_of_at": context.now.isoformat(),
        })
    def select_target(self, context: StageContext) -> StageOutcome:
        """따라갈 System 목표를 고른다. 같은 목표로는 한 번만 승인을 묻는다."""
        session_wait = self._session_wait(context)
        if session_wait is not None:
            return session_wait
        target = self.system_store.latest_target(approved_only=True)
        if target is None:
            return StageOutcome.waiting(resume_after_seconds=60 * 60, metadata={"reason": "no_system_target"})
        if _ID_PATTERNS["target_id"].fullmatch(str(target.target_id)) is None:
            raise RuntimeError("System target ID is invalid")
        if self.approval_repository.is_system_target_followed(target.target_id):
            return StageOutcome.skipped({"target_id": target.target_id, "reason": "system_target_already_asked"})
        return StageOutcome.succeeded({"target_id": target.target_id})
    def follow(self, context: StageContext) -> StageOutcome:
        """새 Toss 계좌 스냅샷으로 `System 목표 − 실제 계좌` 제안을 기록한다. 주문은 아직 없다."""
        session_wait = self._session_wait(context)
        if session_wait is not None:
            return session_wait
        target_id = metadata_id(context, stage_id="select_target", key="target_id")
        outcome = self.follow_target(
            target_id=target_id,
            store=self.system_store,
            repository=self.decision_repository,
            now=self.now(),
        )
        metadata = {"target_id": target_id, "status": outcome.status, "reason": outcome.reason}
        if outcome.status != "planned":
            return StageOutcome.skipped(metadata)
        risk_id = str(outcome.risk_decision_id)
        if _ID_PATTERNS["risk_decision_id"].fullmatch(risk_id) is None:
            raise RuntimeError("follow did not return a valid risk decision ID")
        return StageOutcome.succeeded({
            **metadata,
            "proposal_id": str(outcome.proposal_id),
            "risk_decision_id": risk_id,
            "account_snapshot_id": str(outcome.account_snapshot_id or ""),
            "constructed_at": self.now().isoformat(),
        })
    def run_system_portfolio(self, context: StageContext) -> StageOutcome:
        """승인 여부와 무관하게 System Portfolio를 평가하고 필요하면 목표비중을 다시 만든다."""
        self.command_runner.run(PythonModuleCommand(
            "investment_agent.operations.commands.system_portfolio",
            ("--as-of", context.now.isoformat()),
            self.timeouts.get("system_portfolio", 30 * 60),
        ), stop_event=context.stop_event)
        return StageOutcome.succeeded({"system_portfolio_run_at": self.now().isoformat()})
    def reanalyze_events(self, context: StageContext) -> StageOutcome:
        """새 공시·고영향 사건·검증된 글로벌 사건이 있는 보유 종목만 곧바로 다시 분석한다."""
        self.command_runner.run(PythonModuleCommand(
            "investment_agent.operations.commands.event_reanalysis",
            ("--as-of", context.now.isoformat()),
            self.timeouts.get("analysis", 2 * 60 * 60),
        ), stop_event=context.stop_event)
        return StageOutcome.succeeded({"event_reanalysis_at": self.now().isoformat()})
    def update_performance(self, context: StageContext) -> StageOutcome:
        """계좌와 판단 성과를 각각 원장 사실로 집계한다."""
        self.command_runner.run(PythonModuleCommand(
            "investment_agent.operations.commands.update_performance",
            ("--as-of", context.now.isoformat()),
            self.timeouts.get("update_performance", 10 * 60),
        ), stop_event=context.stop_event)
        return StageOutcome.succeeded({"performance_updated_at": self.now().isoformat()})
