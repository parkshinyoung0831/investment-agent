"""외부 dead-man 점검이 읽을 수 있는 heartbeat·stale 판정."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from investment_agent.platform.serialization import parse_datetime
from investment_agent.operations.harness.runtime import JobRegistry
from investment_agent.operations.harness.state import JsonStateStore


@dataclass(frozen=True)
class HealthReport:
    process_status: str
    process_heartbeat_at: str | None
    stale_jobs: tuple[str, ...]
    waiting_jobs: tuple[str, ...]
    paused_jobs: tuple[str, ...]
    failed_jobs: tuple[str, ...]
    healthy: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_health(
    *,
    store: JsonStateStore,
    registry: JobRegistry,
    now: datetime,
    process_stale_after_seconds: float = 120.0,
) -> HealthReport:
    state = store.load()
    now_utc = now.astimezone(timezone.utc)
    heartbeat = state.process_heartbeat_at
    if heartbeat is None:
        process_status = "never_started"
    elif state.stopped_cleanly:
        process_status = "stopped"
    elif (now_utc - parse_datetime(heartbeat)).total_seconds() > process_stale_after_seconds:
        process_status = "stale"
    else:
        process_status = "running"

    stale: list[str] = []
    waiting: list[str] = []
    paused: list[str] = []
    failed: list[str] = []
    for job_id, job in state.jobs.items():
        definition = registry.get(job_id)
        stale_after = definition.stale_after_seconds if definition is not None else 180.0
        if job.active and (now_utc - parse_datetime(job.heartbeat_at)).total_seconds() > stale_after:
            stale.append(job_id)
        if job.status == "waiting":
            waiting.append(job_id)
        elif job.status == "paused":
            paused.append(job_id)
        elif job.status == "failed":
            failed.append(job_id)
    healthy = process_status == "running" and not stale and not failed
    return HealthReport(
        process_status=process_status,
        process_heartbeat_at=heartbeat,
        stale_jobs=tuple(sorted(stale)),
        waiting_jobs=tuple(sorted(waiting)),
        paused_jobs=tuple(sorted(paused)),
        failed_jobs=tuple(sorted(failed)),
        healthy=healthy,
    )
