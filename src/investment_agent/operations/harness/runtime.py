"""job 등록, 일정 판정, stage 전이를 담당하는 단일 프로세스 scheduler."""
from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from threading import Event

from investment_agent.platform.serialization import parse_datetime
from investment_agent.operations.harness.contracts import (
    HarnessMode,
    JobDefinition,
    StageContext,
    StageOutcome,
)
from investment_agent.operations.harness.kill_switches import KillSwitches
from investment_agent.operations.harness.reporting import HarnessReporter
from investment_agent.operations.harness.sanitize import sanitized
from investment_agent.operations.harness.state import (
    HarnessState,
    JobRuntime,
    JsonStateStore,
    StageRuntime,
    recover_interrupted_jobs,
    utc_iso,
)


def _run_id(job_id: str, scheduled_at: str) -> str:
    digest = hashlib.sha256(f"{job_id}|{scheduled_at}".encode()).hexdigest()[:24]
    return f"run_{digest}"


def _idempotency_key(run_id: str, stage_id: str) -> str:
    return hashlib.sha256(f"{run_id}|{stage_id}".encode()).hexdigest()


class JobRegistry:
    """callback을 상태 파일과 분리해 프로세스 시작 때 명시적으로 등록한다."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobDefinition] = {}

    def register(self, definition: JobDefinition) -> None:
        if definition.job_id in self._jobs:
            raise ValueError(f"duplicate harness job: {definition.job_id}")
        self._jobs[definition.job_id] = definition

    def definitions(self) -> tuple[JobDefinition, ...]:
        return tuple(self._jobs[key] for key in sorted(self._jobs))

    def get(self, job_id: str) -> JobDefinition | None:
        return self._jobs.get(job_id)


class HarnessScheduler:
    """한 tick 안에서 성공 stage를 진행하고 waiting·오류·kill에서 멈춘다."""

    def __init__(
        self,
        *,
        registry: JobRegistry,
        store: JsonStateStore,
        mode: HarnessMode = HarnessMode.ANALYSIS_ONLY,
        environ: Mapping[str, str] | None = None,
        reporter: HarnessReporter | None = None,
        stop_event: Event | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.mode = mode
        self.environ = environ if environ is not None else os.environ
        self.reporter = reporter or HarnessReporter()
        self.stop_event = stop_event or Event()
        self.state = self.store.load()
        self.started = False

    def start(self, *, now: datetime, process_id: int | None = None) -> tuple[str, ...]:
        if self.started:
            raise RuntimeError("harness scheduler is already started")
        recovered = recover_interrupted_jobs(self.state, now=now)
        timestamp = utc_iso(now)
        self.state.process_id = process_id if process_id is not None else os.getpid()
        self.state.process_started_at = timestamp
        self.state.process_heartbeat_at = timestamp
        self.state.stopped_at = None
        self.state.stopped_cleanly = False
        self.store.save(self.state)
        self.started = True
        self.reporter.event(
            "scheduler_started",
            mode=self.mode.value,
            recovered_jobs=list(recovered),
            process_id=self.state.process_id,
        )
        return recovered

    @staticmethod
    def _is_due(job: JobRuntime | None, definition: JobDefinition, now: datetime) -> bool:
        if job is None:
            return True
        if not job.terminal:
            return False
        anchor = parse_datetime(job.completed_at or job.started_at)
        return now.astimezone(timezone.utc) >= anchor + timedelta(
            seconds=definition.interval_seconds
        )

    @staticmethod
    def _new_job(definition: JobDefinition, now: datetime) -> JobRuntime:
        scheduled_at = utc_iso(now)
        return JobRuntime(
            job_id=definition.job_id,
            run_id=_run_id(definition.job_id, scheduled_at),
            status="pending",
            scheduled_at=scheduled_at,
            started_at=scheduled_at,
            heartbeat_at=scheduled_at,
            stages={item.stage_id: StageRuntime() for item in definition.stages},
        )

    @staticmethod
    def _next_stage(job: JobRuntime, definition: JobDefinition):
        for stage in definition.stages:
            if job.stages[stage.stage_id].status not in {"succeeded", "skipped"}:
                return stage
        return None

    def tick(self, *, now: datetime) -> HarnessState:
        if not self.started:
            raise RuntimeError("harness scheduler must be started before tick")
        timestamp = utc_iso(now)
        self.state.process_heartbeat_at = timestamp
        switches = KillSwitches(self.environ)
        for definition in self.registry.definitions():
            job = self.state.jobs.get(definition.job_id)
            if switches.job_blocked(definition.job_id, definition.kill_switch_env):
                if job is not None and job.active:
                    changed = job.status != "paused" or job.pause_reason != "job_kill_switch"
                    job.status = "paused"
                    job.pause_reason = "job_kill_switch"
                    job.heartbeat_at = timestamp
                    if changed:
                        self.reporter.event("job_paused", job_id=job.job_id, reason=job.pause_reason)
                continue
            if self._is_due(job, definition, now):
                job = self._new_job(definition, now)
                self.state.jobs[definition.job_id] = job
                self.reporter.event("job_created", job_id=job.job_id, run_id=job.run_id)
            if job is None or job.terminal:
                continue
            if job.status == "paused" and job.pause_reason == "job_kill_switch":
                job.status = "pending"
                job.pause_reason = None
            job.heartbeat_at = timestamp
            self._advance(job=job, definition=definition, now=now, switches=switches)
        self.store.save(self.state)
        return self.state

    def update_process_heartbeat(self, now: datetime | None = None) -> None:
        if not self.started:
            return
        timestamp = utc_iso(now or datetime.now(timezone.utc))
        self.state.process_heartbeat_at = timestamp
        for job in self.state.jobs.values():
            if job.active:
                job.heartbeat_at = timestamp
        self.store.save(self.state)

    def _advance(
        self,
        *,
        job: JobRuntime,
        definition: JobDefinition,
        now: datetime,
        switches: KillSwitches,
    ) -> None:
        timestamp = utc_iso(now)
        while not self.stop_event.is_set():
            stage_def = self._next_stage(job, definition)
            if stage_def is None:
                job.status = "succeeded"
                job.stage = None
                job.completed_at = timestamp
                job.pause_reason = None
                self.reporter.event("job_succeeded", job_id=job.job_id, run_id=job.run_id)
                return
            runtime = job.stages[stage_def.stage_id]
            job.stage = stage_def.stage_id
            if runtime.status == "failed":
                job.status = "failed"
                job.completed_at = timestamp
                return
            if runtime.status == "waiting" and runtime.resume_at is not None:
                if parse_datetime(runtime.resume_at) > now.astimezone(timezone.utc):
                    job.status = "waiting"
                    return
                runtime.status = "pending"
                runtime.resume_at = None

            from investment_agent.operations.harness.emergency import is_execution_locked_down
            lockdown_block = stage_def.trading_sensitive and is_execution_locked_down(
                self.store.path.parent
            )
            mode_block = (
                stage_def.approval_workflow_only
                and self.mode == HarnessMode.ANALYSIS_ONLY
            )
            sensitive_block = stage_def.trading_sensitive and switches.trading_blocked
            if lockdown_block or mode_block or sensitive_block:
                reason = (
                    "execution_lockdown"
                    if lockdown_block
                    else "analysis_only_mode"
                    if mode_block
                    else "trading_kill_switch"
                )
                changed = job.status != "paused" or job.pause_reason != reason
                job.status = "paused"
                job.pause_reason = reason
                if changed:
                    self.reporter.event(
                        "stage_blocked",
                        job_id=job.job_id,
                        run_id=job.run_id,
                        stage_id=stage_def.stage_id,
                        reason=job.pause_reason,
                    )
                return

            runtime.status = "running"
            runtime.attempts += 1
            runtime.started_at = timestamp
            runtime.resume_at = None
            job.status = "running"
            job.pause_reason = None
            job.heartbeat_at = timestamp
            self.store.save(self.state)
            self.reporter.event(
                "stage_started",
                job_id=job.job_id,
                run_id=job.run_id,
                stage_id=stage_def.stage_id,
                attempt=runtime.attempts,
            )
            context = StageContext(
                job_id=job.job_id,
                run_id=job.run_id,
                stage_id=stage_def.stage_id,
                attempt=runtime.attempts,
                idempotency_key=_idempotency_key(job.run_id, stage_def.stage_id),
                now=now,
                stop_event=self.stop_event,
                prior_metadata=dict(runtime.metadata),
                completed_metadata={
                    stage_id: dict(stage.metadata)
                    for stage_id, stage in job.stages.items()
                    if stage.status in {"succeeded", "skipped"}
                },
            )
            try:
                outcome = stage_def.handler(context)
                if not isinstance(outcome, StageOutcome):
                    raise TypeError("stage handler must return StageOutcome")
            except Exception as exc:  # noqa: BLE001 - retry 정책이 handler 오류를 소유한다
                # 외부 adapter 예외 문구에는 token·URL이 섞일 수 있어 타입만 영구 기록한다.
                runtime.last_error = type(exc).__name__
                runtime.metadata = {}
                if runtime.attempts >= stage_def.max_attempts:
                    runtime.status = "failed"
                    runtime.completed_at = timestamp
                    job.status = "failed"
                    job.completed_at = timestamp
                else:
                    runtime.status = "waiting"
                    runtime.resume_at = utc_iso(
                        now + timedelta(seconds=stage_def.retry_delay_seconds)
                    )
                    job.status = "waiting"
                self.store.save(self.state)
                self.reporter.error(
                    "stage_failed",
                    job_id=job.job_id,
                    run_id=job.run_id,
                    stage_id=stage_def.stage_id,
                    attempt=runtime.attempts,
                    terminal=runtime.status == "failed",
                    error=runtime.last_error,
                )
                return

            runtime.metadata = dict(sanitized(outcome.metadata))
            runtime.last_error = None
            if outcome.status == "waiting":
                runtime.status = "waiting"
                runtime.resume_at = utc_iso(
                    now + timedelta(seconds=float(outcome.resume_after_seconds))
                )
                job.status = "waiting"
                self.store.save(self.state)
                self.reporter.event(
                    "stage_waiting",
                    job_id=job.job_id,
                    run_id=job.run_id,
                    stage_id=stage_def.stage_id,
                    resume_at=runtime.resume_at,
                )
                return
            runtime.status = outcome.status
            runtime.completed_at = timestamp
            runtime.resume_at = None
            job.status = "pending"
            self.store.save(self.state)
            self.reporter.event(
                "stage_completed",
                job_id=job.job_id,
                run_id=job.run_id,
                stage_id=stage_def.stage_id,
                status=outcome.status,
            )

    def shutdown(self, *, now: datetime) -> None:
        if not self.started:
            return
        timestamp = utc_iso(now)
        for job in self.state.jobs.values():
            if job.status != "running" or job.stage is None:
                continue
            runtime = job.stages[job.stage]
            if runtime.status == "running":
                runtime.status = "pending"
                runtime.last_error = "graceful_shutdown_before_stage_checkpoint"
            job.status = "pending"
            job.pause_reason = "graceful_shutdown"
            job.heartbeat_at = timestamp
        self.state.process_heartbeat_at = timestamp
        self.state.stopped_at = timestamp
        self.state.stopped_cleanly = True
        self.store.save(self.state)
        self.started = False
        self.reporter.event("scheduler_stopped", process_id=self.state.process_id)
