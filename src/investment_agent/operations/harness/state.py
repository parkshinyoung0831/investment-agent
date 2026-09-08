"""DB 없이 재시작 복구에 쓰는 작은 로컬 JSON checkpoint."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from investment_agent.platform.serialization import canonical_json, parse_datetime
from investment_agent.operations.harness.sanitize import sanitized

STATE_VERSION = 1
_TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled"}
_ACTIVE_JOB_STATES = {"pending", "running", "waiting", "paused"}
_STAGE_STATES = {"pending", "running", "waiting", "succeeded", "skipped", "failed"}


class StateCorruptionError(RuntimeError):
    """checkpoint를 임의 초기화하지 않고 운영자가 확인해야 하는 경우다."""


def utc_iso(value: datetime | None = None) -> str:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("state timestamps must include a timezone")
    return moment.astimezone(timezone.utc).isoformat()


@dataclass
class StageRuntime:
    status: str = "pending"
    attempts: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    resume_at: str | None = None
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.status not in _STAGE_STATES:
            raise StateCorruptionError(f"invalid stage state: {self.status}")
        if not isinstance(self.attempts, int) or self.attempts < 0:
            raise StateCorruptionError("stage attempts must be non-negative")
        for value in (self.started_at, self.completed_at, self.resume_at):
            if value is not None:
                parse_datetime(value)
        if not isinstance(self.metadata, dict):
            raise StateCorruptionError("stage metadata must be a mapping")


@dataclass
class JobRuntime:
    job_id: str
    run_id: str
    status: str
    scheduled_at: str
    started_at: str
    heartbeat_at: str
    stages: dict[str, StageRuntime]
    stage: str | None = None
    completed_at: str | None = None
    pause_reason: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL_JOB_STATES

    @property
    def active(self) -> bool:
        return self.status in _ACTIVE_JOB_STATES

    def validate(self) -> None:
        if self.status not in _TERMINAL_JOB_STATES | _ACTIVE_JOB_STATES:
            raise StateCorruptionError(f"invalid job state: {self.status}")
        for value in (self.scheduled_at, self.started_at, self.heartbeat_at, self.completed_at):
            if value is not None:
                parse_datetime(value)
        if self.stage is not None and self.stage not in self.stages:
            raise StateCorruptionError("stage is absent from stage state")
        for stage in self.stages.values():
            stage.validate()


@dataclass
class HarnessState:
    version: int = STATE_VERSION
    process_id: int | None = None
    process_started_at: str | None = None
    process_heartbeat_at: str | None = None
    stopped_at: str | None = None
    stopped_cleanly: bool = True
    recovery_count: int = 0
    jobs: dict[str, JobRuntime] = field(default_factory=dict)

    def validate(self) -> None:
        if self.version != STATE_VERSION:
            raise StateCorruptionError(f"unsupported state version: {self.version}")
        if not isinstance(self.recovery_count, int) or self.recovery_count < 0:
            raise StateCorruptionError("recovery_count must be non-negative")
        for value in (self.process_started_at, self.process_heartbeat_at, self.stopped_at):
            if value is not None:
                parse_datetime(value)
        for job_id, job in self.jobs.items():
            if job_id != job.job_id:
                raise StateCorruptionError("job state key does not match job_id")
            job.validate()

    def to_dict(self) -> dict[str, Any]:
        return sanitized(asdict(self))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HarnessState":
        try:
            jobs: dict[str, JobRuntime] = {}
            for job_id, raw_job in dict(payload.get("jobs") or {}).items():
                raw = dict(raw_job)
                if "current_stage" in raw and "stage" not in raw:
                    raw["stage"] = raw.pop("current_stage")
                elif "current_stage" in raw:
                    raw.pop("current_stage")
                raw["stages"] = {
                    str(stage_id): StageRuntime(**dict(stage))
                    for stage_id, stage in dict(raw.get("stages") or {}).items()
                }
                jobs[str(job_id)] = JobRuntime(**raw)
            state = cls(
                version=int(payload.get("version", 0)),
                process_id=payload.get("process_id"),
                process_started_at=payload.get("process_started_at"),
                process_heartbeat_at=payload.get("process_heartbeat_at"),
                stopped_at=payload.get("stopped_at"),
                stopped_cleanly=bool(payload.get("stopped_cleanly", False)),
                recovery_count=int(payload.get("recovery_count", 0)),
                jobs=jobs,
            )
            state.validate()
            return state
        except (KeyError, TypeError, ValueError, StateCorruptionError) as exc:
            if isinstance(exc, StateCorruptionError):
                raise
            raise StateCorruptionError(f"invalid harness state: {exc}") from exc


class JsonStateStore:
    """같은 디렉터리의 임시 파일을 원자적으로 교체한다."""

    def __init__(self, path: Path | str):
        self.path = Path(path).resolve()

    def load(self) -> HarnessState:
        if not self.path.exists():
            return HarnessState()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateCorruptionError(f"cannot read harness state: {exc}") from exc
        if not isinstance(payload, dict):
            raise StateCorruptionError("harness state root must be an object")
        return HarnessState.from_dict(payload)

    def save(self, state: HarnessState) -> None:
        state.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temp.write_text(canonical_json(state.to_dict()) + "\n", encoding="utf-8")
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()


def recover_interrupted_jobs(state: HarnessState, *, now: datetime) -> tuple[str, ...]:
    """프로세스가 죽을 때 running이던 stage를 같은 멱등키의 pending으로 되돌린다."""
    recovered: list[str] = []
    timestamp = utc_iso(now)
    for job in state.jobs.values():
        if job.status != "running":
            continue
        if job.stage is not None:
            stage = job.stages[job.stage]
            if stage.status == "running":
                stage.status = "pending"
                stage.last_error = "recovered_after_unclean_restart"
                stage.resume_at = timestamp
        job.status = "pending"
        job.heartbeat_at = timestamp
        job.pause_reason = "recovered_after_unclean_restart"
        recovered.append(job.job_id)
    if recovered:
        state.recovery_count += 1
    return tuple(sorted(recovered))
