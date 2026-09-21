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
    # 정의가 지금 레지스트리에 없는 job(옛 배포의 잔재). 진행할 수 없으므로 paused·stale 집계에서 뺀다.
    orphan_jobs: tuple[str, ...] = ()
    # 마지막 실행에서 어떤 단계가 오류로 건너뛰어진 job. `skipped`는 다음 단계를 살리려는 선택이라 job은 성공으로
    # 끝난다 — 그 성공에 가려진 영구 실패(자격증명 삭제·403)를 드러내는 정보이며 healthy는 바꾸지 않는다.
    degraded_jobs: tuple[str, ...] = ()

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
    orphans: list[str] = []
    degraded: list[str] = []
    for job_id, job in state.jobs.items():
        definition = registry.get(job_id)
        if definition is None:
            orphans.append(job_id)
            continue
        if any(stage.status == "skipped" and stage.metadata.get("error_type") for stage in job.stages.values()):
            degraded.append(job_id)
        stale_after = definition.stale_after_seconds
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
        orphan_jobs=tuple(sorted(orphans)),
        degraded_jobs=tuple(sorted(degraded)),
    )
