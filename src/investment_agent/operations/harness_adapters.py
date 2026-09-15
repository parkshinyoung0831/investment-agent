"""generic 하네스를 실제 AI 판단·Discord 승인·Toss entry에 연결한다.

`harness/` 안에 두지 않는다. 그 폴더는 실행·broker를 전혀 모르는 것이
불변이고(`test_harness_source_has_no_execution_or_broker_dependency`가
`harness/*.py`를 통째로 훑는다), 이 파일이 바로 그 경계를 넘는 어댑터다.
"""
from __future__ import annotations

import math
import json
from tempfile import TemporaryDirectory
import os
import re
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import parse_datetime
from investment_agent.operations.harness.commands import (
    ModuleCommandRunner,
    PythonModuleCommand,
    SubprocessModuleRunner,
)
from investment_agent.operations.harness.contracts import StageContext, StageOutcome
from investment_agent.operations.harness.market_schedule import SessionWindow

log = get_logger(__name__)


def follow_system_target(*, target_id: str, store: Any, repository: Any, now: datetime) -> Any:
    """System 목표 하나를 새 Toss 계좌 스냅샷과 비교해 추종 제안을 기록한다.

    계좌 조회는 여기서만 한다 — System 목표는 이미 정해진 뒤다.
    """
    from investment_agent.execution.brokers.toss.client import resolve_account_seq
    from investment_agent.execution.orders.toss_snapshot import capture_toss_account_snapshot
    from investment_agent.trading.my_portfolio import plan_follow

    target = store.latest_target(approved_only=True)
    if target is None or target.target_id != target_id:
        raise RuntimeError("the selected System target is no longer the latest approved target")
    if not repository.has_approved_promotion(target.model_artifact_id, "live"):
        # 승격되지 않은 조합으로 브로커를 부르지 않는다.
        raise RuntimeError("System target model artifact has not been manually promoted to live")
    snapshot = capture_toss_account_snapshot(account_seq=resolve_account_seq(None))
    return plan_follow(repository, target=target, snapshot=snapshot, now=now)

_ID_PATTERNS = {
    "batch_id": re.compile(r"^signal_batch_[0-9a-f]{24}$"),
    "target_id": re.compile(r"^system_target_[0-9a-f]{24}$"),
    "risk_decision_id": re.compile(r"^risk_[0-9a-f]{24}$"),
    "intent_id": re.compile(r"^intent_[0-9a-f]{24}$"),
    "approval_id": re.compile(r"^approval_[0-9a-f]{32}$"),
}
_MODULES = frozenset({
    # System Portfolio. 실계좌·승인 원장과 표가 다르고 주문을 내지 않는다.
    "investment_agent.operations.commands.system_portfolio",
    # 사건 기반 즉시 재분석. 결과는 보통의 signal batch이고 주문은 내지 않는다.
    "investment_agent.operations.commands.event_reanalysis",
    # ML 후보 재학습·비교. 채택 파일은 쓰지 않는다.
    "investment_agent.research.commands.ml_challengers",
    "investment_agent.research.commands.build_decision_experiences",
    "investment_agent.operations.commands.update_performance",
    "investment_agent.trading.decision.analysis",
    # 학습 원장 생산. 주문이 아니라 데이터 수집이라 거래 kill switch와 무관하다.
    "investment_agent.research.commands.build_valuations",
    "investment_agent.research.commands.build_features",
    "investment_agent.research.commands.build_labels",
    "investment_agent.research.commands.build_training_samples",
    "investment_agent.research.commands.build_events",
    "investment_agent.research.commands.evaluate",
    # 자동매매 보고서. 원장을 읽어 Discord로만 내보내고 판단·주문 원장은 건드리지 않는다.
    "investment_agent.operations.commands.notify",
    "investment_agent.research.commands.continuous_retrain",
    "investment_agent.operations.commands.watch_earnings",
    "investment_agent.operations.commands.request_toss_approval",
    "investment_agent.operations.commands.execute_toss_live",
    "investment_agent.operations.commands.reconcile_toss",
    "investment_agent.operations.commands.capture_toss_risk_snapshot",
})
# broker·승인 비밀을 받는 모듈. LLM을 부르지 않는 주문·대사·계좌·시세 조회뿐이다.
# 여기 없는 모듈은 판단 범위로 떠서 `.env`를 읽어도 그 비밀이 지워진다.
EXECUTION_MODULES = frozenset({
    "investment_agent.operations.commands.request_toss_approval",
    "investment_agent.operations.commands.execute_toss_live",
    "investment_agent.operations.commands.reconcile_toss",
    "investment_agent.operations.commands.capture_toss_risk_snapshot",
})


class DecisionRepositoryPort(Protocol):
    def signal_batch_id_for_as_of(self, *, as_of_at: datetime) -> str: ...


class ApprovalRepositoryPort(Protocol):
    def approval_for_intent(self, intent_id: str) -> Any | None: ...
    def is_system_target_followed(self, target_id: str) -> bool: ...


class SystemTargetPort(Protocol):
    def latest_target(self, *, approved_only: bool = False) -> Any | None: ...


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _positive_float(
    environ: Mapping[str, str],
    name: str,
    default: float,
    *,
    maximum: float,
) -> float:
    raw = str(environ.get(name) or "").strip()
    try:
        value = default if not raw else float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or value <= 0 or value > maximum:
        raise RuntimeError(f"{name} is outside its safe range")
    return value


def _positive_int(
    environ: Mapping[str, str],
    name: str,
    default: int,
    *,
    maximum: int,
) -> int:
    raw = str(environ.get(name) or "").strip()
    try:
        value = default if not raw else int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < 1 or value > maximum:
        raise RuntimeError(f"{name} is outside its safe range")
    return value


def _wall_time(environ: Mapping[str, str], name: str, default: time) -> time:
    raw = str(environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        parsed = time.fromisoformat(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must use HH:MM") from exc
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise RuntimeError(f"{name} must use minute-precision New York wall time")
    return parsed


def _metadata_id(
    context: StageContext,
    *,
    stage_id: str,
    key: str,
    required: bool = True,
) -> str | None:
    value = context.completed_metadata.get(stage_id, {}).get(key)
    if value is None and not required:
        return None
    text = str(value or "")
    pattern = _ID_PATTERNS[key]
    if pattern.fullmatch(text) is None:
        raise RuntimeError(f"prior {key} is missing or invalid")
    return text


class ProductionInvestmentAdapters:
    """ID를 metadata로 넘기고 모든 주문 mutation은 execution entry에만 맡긴다."""

    def __init__(
        self,
        *,
        command_runner: ModuleCommandRunner,
        decision_repository: DecisionRepositoryPort,
        approval_repository: ApprovalRepositoryPort,
        system_store: SystemTargetPort,
        follow_target: Callable[..., Any],
        create_execution_intent: Callable[..., Any],
        now: Callable[[], datetime] = _clock,
        session_window: SessionWindow = SessionWindow(),
        risk_window: SessionWindow = SessionWindow(time(9, 15), time(16, 30)),
        analysis_limit: int = 5,
        approval_ttl_minutes: int = 15,
        approval_poll_seconds: float = 15.0,
        timeouts: Mapping[str, float] | None = None,
        is_background_enabled: bool = False,
    ) -> None:
        if analysis_limit < 1 or analysis_limit > 500:
            raise ValueError("analysis_limit must be between 1 and 500")
        if approval_ttl_minutes < 1 or approval_ttl_minutes > 240:
            raise ValueError("approval_ttl_minutes must be between 1 and 240")
        if not math.isfinite(approval_poll_seconds) or approval_poll_seconds <= 0:
            raise ValueError("approval_poll_seconds must be finite and positive")
        self.command_runner = command_runner
        self.decision_repository = decision_repository
        self.approval_repository = approval_repository
        self.system_store = system_store
        self.follow_target = follow_target
        self.create_execution_intent = create_execution_intent
        self.now = now
        self.session_window = session_window
        self.risk_window = risk_window
        self.analysis_limit = analysis_limit
        self.approval_ttl_minutes = approval_ttl_minutes
        self.approval_poll_seconds = float(approval_poll_seconds)
        self.timeouts = dict(timeouts or {})
        if is_background_enabled:
            from investment_agent.operations.harness.background import BackgroundStages
            self._background=BackgroundStages()
            for name in ('analysis','build_valuations','build_features','build_labels','build_training_samples',
                         'build_events','evaluate_decisions','build_decision_experiences','continuous_learning',
                         'run_system_portfolio','update_performance','notify_reports','notify_investment'):
                setattr(self,name,self._background.wrap(getattr(self,name)))

    @classmethod
    def from_env(
        cls,
        *,
        repository_root: Path | str,
        environ: Mapping[str, str] | None = None,
    ) -> "ProductionInvestmentAdapters":
        values = os.environ if environ is None else environ
        # 무거운 파이프라인 import는 dry-run 계획 생성 이후 실제 registry를 만들 때만 한다.
        from investment_agent.trading.supabase_repository import SupabaseRepository
        from investment_agent.trading.system.store import SystemPortfolioStore
        from investment_agent.operations.commands.create_execution_intent import create_execution_intent
        from investment_agent.execution.db import ExecutionRepository

        timeouts = {
            "analysis": _positive_float(
                values, "HARNESS_ANALYSIS_TIMEOUT_SEC", 2 * 60 * 60, maximum=12 * 60 * 60,
            ),
            "approval_request": _positive_float(
                values, "HARNESS_APPROVAL_REQUEST_TIMEOUT_SEC", 180, maximum=15 * 60,
            ),
            "approval_worker": _positive_float(
                values, "HARNESS_EXECUTION_TIMEOUT_SEC", 10 * 60, maximum=30 * 60,
            ),
            "risk_snapshot": _positive_float(
                values, "HARNESS_RISK_SNAPSHOT_TIMEOUT_SEC", 180, maximum=15 * 60,
            ),
            "reconcile": _positive_float(
                values, "HARNESS_RECONCILE_TIMEOUT_SEC", 180, maximum=15 * 60,
            ),
            # 관심종목 실적 감시. 평시에는 1분 안에 끝나고, 정식 보고서 적재만 더 길다.
            "earnings_watch": _positive_float(
                values, "HARNESS_EARNINGS_WATCH_TIMEOUT_SEC", 12 * 60, maximum=15 * 60,
            ),
            # 503종목 x 4단계라 느리다. 하루 한 번이므로 넉넉히 준다.
            "build_valuations": _positive_float(
                values, "HARNESS_BUILD_VALUATIONS_TIMEOUT_SEC", 60 * 60, maximum=4 * 60 * 60,
            ),
            # 종목당 8개 도메인을 조회한다. 실측 ~9초/종목이라 503종목이면 75분 안팎이다.
            "build_features": _positive_float(
                values, "HARNESS_BUILD_FEATURES_TIMEOUT_SEC", 2 * 60 * 60, maximum=4 * 60 * 60,
            ),
            "build_labels": _positive_float(
                values, "HARNESS_BUILD_LABELS_TIMEOUT_SEC", 60 * 60, maximum=4 * 60 * 60,
            ),
            "build_training_samples": _positive_float(
                values, "HARNESS_BUILD_TRAINING_SAMPLES_TIMEOUT_SEC", 60 * 60, maximum=4 * 60 * 60,
            ),
            # 로컬 DuckDB만 읽고 파생물만 올린다. 네트워크 호출이 없어 짧다.
            "build_events": _positive_float(
                values, "HARNESS_BUILD_EVENTS_TIMEOUT_SEC", 15 * 60, maximum=60 * 60,
            ),
            # 성숙한 판단만 채점하므로 하루치 증분은 작다.
            "evaluate_decisions": _positive_float(
                values, "HARNESS_EVALUATE_DECISIONS_TIMEOUT_SEC", 30 * 60, maximum=2 * 60 * 60,
            ),
            # embed 몇 장을 올릴 뿐이라 짧다. rate limit 대기까지만 감안한다.
            "notify_investment": _positive_float(
                values, "HARNESS_NOTIFY_INVESTMENT_TIMEOUT_SEC", 5 * 60, maximum=30 * 60,
            ),
        }
        runner = SubprocessModuleRunner(
            repository_root=repository_root,
            allowed_modules=tuple(sorted(_MODULES)),
            execution_modules=tuple(sorted(EXECUTION_MODULES)),
            environ=values,
        )
        window = SessionWindow(
            start=_wall_time(values, "HARNESS_NY_SESSION_START", time(9, 40)),
            end=_wall_time(values, "HARNESS_NY_SESSION_END", time(14, 30)),
        )
        risk_window = SessionWindow(
            start=_wall_time(values, "HARNESS_NY_RISK_START", time(9, 15)),
            end=_wall_time(values, "HARNESS_NY_RISK_END", time(16, 30)),
        )
        return cls(
            is_background_enabled=True,
            command_runner=runner,
            decision_repository=SupabaseRepository(),
            approval_repository=ExecutionRepository(),
            system_store=SystemPortfolioStore(),
            follow_target=follow_system_target,
            create_execution_intent=create_execution_intent,
            session_window=window,
            risk_window=risk_window,
            analysis_limit=_positive_int(
                values, "AI_INVESTOR_DAILY_LIMIT", 5, maximum=500,
            ),
            approval_ttl_minutes=_positive_int(
                values, "AI_APPROVAL_TTL_MINUTES", 15, maximum=240,
            ),
            approval_poll_seconds=_positive_float(
                values, "HARNESS_APPROVAL_POLL_SEC", 15, maximum=5 * 60,
            ),
            timeouts=timeouts,
        )

    def _session_wait(self, context: StageContext) -> StageOutcome | None:
        if self.session_window.is_open(context.now):
            return None
        return StageOutcome.waiting(
            resume_after_seconds=self.session_window.seconds_until_open(context.now),
            metadata={"reason": "outside_safe_ny_session"},
        )

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
        target_id = _metadata_id(context, stage_id="select_target", key="target_id")
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

    def execution_intent(self, context: StageContext) -> StageOutcome:
        follow = context.completed_metadata.get("follow", {})
        if follow.get("status") != "planned":
            return StageOutcome.skipped({"reason": "no_follow_plan"})
        risk_id = _metadata_id(
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
        intent_id = _metadata_id(
            context,
            stage_id="execution_intent",
            key="intent_id",
            required=False,
        )
        if intent_id is None:
            return StageOutcome.skipped({"reason": "no_live_intent"})
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
        intent_id = _metadata_id(
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

    def watch(self, context: StageContext) -> StageOutcome:
        """발표 예정 시각 창에서 관심종목 공시를 훑고 알림을 바로 보낸다.

        거래 창(risk_window)으로 막지 않는다 — 주문이 아니라 공시 수집이고, 실적은
        장 시작 전(BMO)과 장 마감 후(AMC)에 나오므로 거래 창으로 자르면 정작
        발표가 몰리는 시간대를 통째로 놓친다. 창 판정은 `--session auto`가 예정
        시각의 신뢰도와 ET 기준으로 직접 하고, 창 밖이면 대상 0건으로 즉시 끝나
        SEC를 때리지 않는다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.operations.commands.watch_earnings",
                ("--session", "auto", "--notify", "--report-notify"),
                self.timeouts.get("earnings_watch", 12 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"watched_at": self.now().isoformat()})

    def build_valuations(self, context: StageContext) -> StageOutcome:
        """PIT 밸류에이션 관측값을 원장에 적재한다.

        live_shadow만 만든다 — 과거 시점은 가격 적재시각과 TTM vintage를 증명할 수
        없어 진입점이 거부한다. feature 단계보다 먼저 둬서 이후 feature 세대가 이
        관측값을 읽을 수 있게 한다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.build_valuations",
                ("--as-of", context.now.isoformat()),
                self.timeouts.get("build_valuations", 60 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"valued_at": self.now().isoformat()})

    def build_features(self, context: StageContext) -> StageOutcome:
        """tracked universe의 PIT feature snapshot을 ResearchStore에 적재한다.

        주문이 아니라 데이터 생산이라 거래 kill switch·거래 창과 무관하게 돈다.
        결과는 versioned `rl_feature_snapshots` dataset에 기록되고, 재실행은 같은 키를
        upsert한다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.build_features",
                ("--as-of", context.now.isoformat()),
                self.timeouts.get("build_features", 60 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"built_at": self.now().isoformat()})

    def build_training_samples(self, context: StageContext) -> StageOutcome:
        """확정된 label을 비용 반영 학습 표본으로 바꿔 쌓는다.

        label 단계 뒤에 붙는다. gross 수익률을 그대로 학습하면 모델이 회전율을
        과대평가하므로, 여기서 왕복 수수료·슬리피지를 적용한 net label을 만든다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.build_training_samples",
                ("--as-of", context.now.isoformat()),
                self.timeouts.get("build_training_samples", 60 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"sampled_at": self.now().isoformat()})

    def _notify(self, context: StageContext, kinds: tuple[str, ...], label: str) -> StageOutcome:
        """알림 발송은 실패해도 판단·주문 결과를 가리지 않는다 (관례 8).

        보고서가 안 나간 것은 되돌릴 수 있지만, 여기서 예외를 올리면 그 회차의
        판단·체결까지 실패로 기록돼 다음 주기가 잘못된 상태에서 시작한다.
        """
        failed: list[str] = []
        for kind in kinds:
            try:
                self.command_runner.run(
                    PythonModuleCommand(
                        "investment_agent.operations.commands.notify",
                        ("--kind", kind),
                        self.timeouts.get("notify_investment", 5 * 60),
                    ),
                    stop_event=context.stop_event,
                )
            except Exception as exc:  # noqa: BLE001 - 알림 실패는 경고로만 남긴다
                failed.append(f"{kind}:{type(exc).__name__}")
                log.warning("%s notification failed kind=%s: %s", label, kind, exc)
        metadata = {"notified_at": self.now().isoformat(), "kinds": list(kinds)}
        if failed:
            return StageOutcome.skipped({**metadata, "failed": failed})
        return StageOutcome.succeeded(metadata)

    def notify_investment(self, context: StageContext) -> StageOutcome:
        """종합 판단과 상위 후보 리포트를 `#투자-리포트`로 보낸다."""
        return self._notify(
            context, ("investment_portfolio", "investment_candidates"), "investment",
        )

    def notify_trades(self, context: StageContext) -> StageOutcome:
        """실제로 나간 주문·체결을 `#매매-기록`으로 보낸다."""
        return self._notify(context, ("investment_trades",), "trade")

    def build_decision_experiences(self, context: StageContext) -> StageOutcome:
        """승인 여부와 무관하게 원본 판단의 확정된 결과를 학습 원장에 기록한다."""
        self.command_runner.run(PythonModuleCommand(
            "investment_agent.research.commands.build_decision_experiences",
            ("--as-of", context.now.isoformat()),
            self.timeouts.get("build_decision_experiences", 60 * 60),
        ), stop_event=context.stop_event)
        return StageOutcome.succeeded({"experiences_built_at": self.now().isoformat()})

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

    def run_ml_challengers(self, context: StageContext) -> StageOutcome:
        """쌓인 feature·label로 ML 후보를 다시 학습하고 champion과 비교해 기록한다(채택은 사람)."""
        self.command_runner.run(PythonModuleCommand(
            "investment_agent.research.commands.ml_challengers",
            ("--as-of", context.now.isoformat()),
            self.timeouts.get("ml_challengers", 3 * 60 * 60),
        ), stop_event=context.stop_event)
        return StageOutcome.succeeded({"ml_challengers_run_at": self.now().isoformat()})

    def update_performance(self, context: StageContext) -> StageOutcome:
        """계좌와 판단 성과를 각각 원장 사실로 집계한다."""
        self.command_runner.run(PythonModuleCommand(
            "investment_agent.operations.commands.update_performance",
            ("--as-of", context.now.isoformat()),
            self.timeouts.get("update_performance", 10 * 60),
        ), stop_event=context.stop_event)
        return StageOutcome.succeeded({"performance_updated_at": self.now().isoformat()})

    def notify_reports(self, context: StageContext) -> StageOutcome:
        """독립 주기에서 누락 보고와 뒤늦게 확정된 체결의 발송을 재시도한다."""
        return self._notify(context, (
            "investment_portfolio", "investment_candidates", "investment_trades", "investment_performance",
        ), "reports")

    def evaluate_decisions(self, context: StageContext) -> StageOutcome:
        """성숙한 과거 Shadow 판단을 SPY 대비 5·20·60 거래일로 채점한다.

        주문이 아니라 채점이라 거래 kill switch와 무관하다. 이 결과가
        `decision_evaluations`에 쌓여야 `CaseMemory`가 다음 판단에 과거 성적을
        넘길 수 있다 — 돌지 않으면 학습 루프가 열린 채로 남는다.
        같은 case의 같은 horizon은 다시 쓰지 않으므로 매일 돌려도 안전하다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.evaluate",
                (),
                self.timeouts.get("evaluate_decisions", 30 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"evaluated_at": self.now().isoformat()})

    def build_events(self, context: StageContext) -> StageOutcome:
        """로컬 뉴스·소셜 원문을 사건과 event feature로 압축해 원장에 남긴다.

        원문은 Supabase로 가지 않는다. 올라가는 것은 사건 단위 요약뿐이라 이 단계가
        없으면 Research local dataset `events`가 비고, 대시보드의 사건 패널도 빈 채로 남는다.
        원천이 90일치 로컬 캐시라 실패해도 나중에 다시 만들 수 있어 맨 뒤에 둔다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.build_events",
                ("--as-of", context.now.isoformat()),
                self.timeouts.get("build_events", 15 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"events_built_at": self.now().isoformat()})

    def build_labels(self, context: StageContext) -> StageOutcome:
        """미래 구간이 끝난 snapshot에만 forward return label을 붙인다.

        feature 적재 뒤에 이어 붙는다. 구간이 아직 열려 있는 snapshot은 건드리지
        않으므로 매일 돌려도 같은 행을 다시 만들지 않는다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.build_labels",
                ("--as-of", context.now.isoformat()),
                self.timeouts.get("build_labels", 60 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"labeled_at": self.now().isoformat()})

    def continuous_learning(self, context: StageContext) -> StageOutcome:
        """자료 대기와 실제 후보 학습을 구분하고 채택 여부를 과장하지 않는다."""
        with TemporaryDirectory() as directory:
            result_path = Path(directory) / 'learning-result.json'
            self.command_runner.run(PythonModuleCommand(
                "investment_agent.research.commands.continuous_retrain",
                ("--as-of", context.now.isoformat(), '--result-path', str(result_path)),
                self.timeouts.get("continuous_learning", 60 * 60),
            ), stop_event=context.stop_event)
            if not result_path.exists():
                raise RuntimeError('learning command did not report its actual status')
            result = json.loads(result_path.read_text(encoding='utf-8'))
        return StageOutcome.skipped(result) if result['status'] == 'pending' else StageOutcome.succeeded(result)


__all__ = ["ProductionInvestmentAdapters", "SessionWindow"]
