"""generic 하네스를 실제 AI 판단·Discord 승인·Toss entry에 연결한다.

`harness/` 안에 두지 않는다. 그 폴더는 실행·broker를 전혀 모르는 것이
불변이고(`test_harness_source_has_no_execution_or_broker_dependency`가
`harness/*.py`를 통째로 훑는다), 이 파일이 바로 그 경계를 넘는 어댑터다.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from investment_agent.operations.harness.commands import (
    ModuleCommandRunner,
    SubprocessModuleRunner,
)
from investment_agent.operations.harness.contracts import StageContext, StageOutcome
from investment_agent.operations.harness.market_schedule import SessionWindow

_MODULES = frozenset({
    "investment_agent.data.market.commands.sync_local_mirror",
    "investment_agent.operations.commands.system_portfolio",
    "investment_agent.operations.commands.event_reanalysis",
    "investment_agent.research.commands.ml_challengers",
    "investment_agent.operations.commands.build_decision_experiences",
    "investment_agent.operations.commands.update_performance",
    "investment_agent.trading.decision.analysis",
    "investment_agent.research.commands.build_valuations",
    "investment_agent.research.commands.build_features",
    "investment_agent.research.commands.build_labels",
    "investment_agent.research.commands.build_training_samples",
    "investment_agent.research.commands.build_events",
    "investment_agent.operations.commands.evaluate_decisions",
    "investment_agent.operations.commands.system_diagnosis",
    "investment_agent.operations.commands.notify",
    "investment_agent.research.commands.continuous_retrain",
    "investment_agent.operations.commands.watch_earnings",
    "investment_agent.operations.commands.econ_calendar_watch_releases",
    "investment_agent.operations.commands.request_toss_approval",
    "investment_agent.operations.commands.execute_toss_live",
    "investment_agent.operations.commands.reconcile_toss",
    "investment_agent.operations.commands.capture_toss_risk_snapshot",
})
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
    environ: Mapping[str, str], name: str, default: float, *, maximum: float,
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
    environ: Mapping[str, str], name: str, default: int, *, maximum: int,
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


from investment_agent.operations.adapters.data import DataAdapters
from investment_agent.operations.adapters.execution import ExecutionAdapters
from investment_agent.operations.adapters.notifications import NotificationAdapters
from investment_agent.operations.adapters.research import ResearchAdapters
from investment_agent.operations.adapters.trading import TradingAdapters, follow_system_target

# 긴 읽기·분석 stage 전부 — 감싸지 않으면 tick 루프를 그 stage가 끝날 때까지 막는다
# (감사 OP2-03). 값이 None인 것은 `self.timeouts`에 단일 키가 없는 stage다(예: `notify_reports`는
# kind별로 따로 시간을 잰다) — 타임아웃 강제 없이 워커 자리만 확보한다.
_BACKGROUND_STAGE_TIMEOUT_KEYS: dict[str, str | None] = {
    "analysis": "analysis",
    "build_valuations": "build_valuations",
    "build_features": "build_features",
    "build_labels": "build_labels",
    "build_training_samples": "build_training_samples",
    "build_events": "build_events",
    "evaluate_decisions": "evaluate_decisions",
    "diagnose_system": "diagnose_system",
    "build_decision_experiences": "build_decision_experiences",
    "continuous_learning": "continuous_learning",
    "run_system_portfolio": "system_portfolio",
    "update_performance": "update_performance",
    "notify_reports": None,
    "notify_investment": "notify_investment",
    # 여기부터는 예전에 감싸는 목록에서 빠졌던 것들이다(감사 OP2-03) — 하나라도 오래 걸리면
    # 1분 주기 job(승인 처리·가격 감시)이 그동안 통째로 멈췄다.
    "watch": "earnings_watch",
    "watch_releases": "econ_release_watch",
    "sync_local_mirror": "sync_local_mirror",
    "risk_snapshot": "risk_snapshot",
    "reconcile": "reconcile",
    "run_ml_challengers": "ml_challengers",
}


class ProductionInvestmentAdapters(
    DataAdapters,
    ResearchAdapters,
    TradingAdapters,
    ExecutionAdapters,
    NotificationAdapters,
):
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
            # 감싸는 stage 수 이상으로 둔다 — 6칸에 13개를 몰아넣던 것(감사 OP2-02)을
            # 워커 부족 자체로는 못 막게 하고, 그래도 갇히면 타임아웃이 실패로 드러낸다.
            self._background=BackgroundStages(max_workers=len(_BACKGROUND_STAGE_TIMEOUT_KEYS))
            for name, timeout_key in _BACKGROUND_STAGE_TIMEOUT_KEYS.items():
                timeout = self.timeouts.get(timeout_key) if timeout_key else None
                setattr(self, name, self._background.wrap(getattr(self, name), timeout_seconds=timeout))
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
            # 발표 시간대에만 돌고 due 지표가 없으면 즉시 끝난다.
            "econ_release_watch": _positive_float(
                values, "HARNESS_ECON_RELEASE_WATCH_TIMEOUT_SEC", 5 * 60, maximum=15 * 60,
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
            # 목표마다 가격 경로를 읽는다. 종목 수백 개의 가격 조회가 대부분이다.
            "diagnose_system": _positive_float(
                values, "HARNESS_DIAGNOSE_SYSTEM_TIMEOUT_SEC", 30 * 60, maximum=2 * 60 * 60,
            ),
            # embed 몇 장을 올릴 뿐이라 짧다. rate limit 대기까지만 감안한다.
            "notify_investment": _positive_float(
                values, "HARNESS_NOTIFY_INVESTMENT_TIMEOUT_SEC", 5 * 60, maximum=30 * 60,
            ),
            # 아래 여섯은 handler 안의 `self.timeouts.get(key, 기본값)` 기본값과 같다 — 예전에는
            # 이 dict에 없어서(값은 있었지만) background wrap의 타임아웃 근거가 없었다(감사 OP2-03).
            "continuous_learning": _positive_float(
                values, "HARNESS_CONTINUOUS_LEARNING_TIMEOUT_SEC", 60 * 60, maximum=4 * 60 * 60,
            ),
            "build_decision_experiences": _positive_float(
                values, "HARNESS_BUILD_DECISION_EXPERIENCES_TIMEOUT_SEC", 60 * 60, maximum=4 * 60 * 60,
            ),
            # 재학습·challenger 비교는 시간이 오래 걸리는 게 정상이라 넉넉히 3시간이다.
            "ml_challengers": _positive_float(
                values, "HARNESS_ML_CHALLENGERS_TIMEOUT_SEC", 3 * 60 * 60, maximum=6 * 60 * 60,
            ),
            "system_portfolio": _positive_float(
                values, "HARNESS_SYSTEM_PORTFOLIO_TIMEOUT_SEC", 30 * 60, maximum=2 * 60 * 60,
            ),
            "update_performance": _positive_float(
                values, "HARNESS_UPDATE_PERFORMANCE_TIMEOUT_SEC", 10 * 60, maximum=30 * 60,
            ),
            "sync_local_mirror": _positive_float(
                values, "HARNESS_SYNC_LOCAL_MIRROR_TIMEOUT_SEC", 60 * 60, maximum=4 * 60 * 60,
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

__all__ = ["ProductionInvestmentAdapters", "SessionWindow"]
