"""대시보드 하네스 상태·역할 분석 요약 계산."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from investment_agent.dashboard.calculations._common import finite_number, parse_datetime_safe

_ACTIVE_JOB_STATES = {"pending", "running", "waiting", "paused"}


def inspect_harness_state(
    state: Mapping[str, Any] | None,
    pid_exists: Callable[[int], bool] | None = None,
    now: datetime | None = None,
    *,
    process_stale_after_seconds: float = 120.0,
    job_stale_after_seconds: float = 180.0,
) -> dict[str, Any]:
    """하네스 JSON을 변경하지 않고 PID·heartbeat·잡 건강 상태로 요약한다.

    반환값은 ``available``, ``process_status``, ``healthy``, ``pid_alive``,
    ``heartbeat_age_seconds``, 정상 종료·recovery·kill-switch 관측 상태, ``jobs``와
    stale/waiting/paused/failed 잡 ID를 포함한다. PID 조회는 주입된 callback만 호출한다.
    """
    base = {
        "available": False,
        "process_status": "state_missing",
        "healthy": False,
        "process_id": None,
        "pid_alive": None,
        "pid_check_error": False,
        "process_started_at": None,
        "process_heartbeat_at": None,
        "heartbeat_age_seconds": None,
        "stopped_at": None,
        "stopped_cleanly": None,
        "recovery_count": None,
        "kill_switch_active": None,
        "jobs": [],
        "stale_jobs": (),
        "waiting_jobs": (),
        "paused_jobs": (),
        "failed_jobs": (),
    }
    if not isinstance(state, Mapping):
        return base
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    process_id_raw = state.get("process_id")
    process_id = int(process_id_raw) if isinstance(process_id_raw, int) and not isinstance(process_id_raw, bool) and process_id_raw > 0 else None
    pid_alive: bool | None = None
    pid_check_error = False
    if process_id is not None and pid_exists is not None:
        try:
            pid_alive = bool(pid_exists(process_id))
        except Exception:  # noqa: BLE001 - 관제 화면은 PID 확인 실패도 상태로 돌려준다.
            pid_check_error = True

    process_threshold = finite_number(process_stale_after_seconds)
    if process_threshold is None or process_threshold <= 0.0:
        process_threshold = 120.0
    default_job_threshold = finite_number(job_stale_after_seconds)
    if default_job_threshold is None or default_job_threshold <= 0.0:
        default_job_threshold = 180.0
    heartbeat = parse_datetime_safe(state.get("process_heartbeat_at"))
    heartbeat_age = (current - heartbeat).total_seconds() if heartbeat is not None else None
    stopped_raw = state.get("stopped_cleanly")
    stopped_cleanly = stopped_raw if isinstance(stopped_raw, bool) else None
    if stopped_cleanly is True:
        process_status = "stopped"
    elif pid_alive is False:
        process_status = "pid_not_alive"
    elif heartbeat is None:
        process_status = "never_started" if process_id is None else "heartbeat_missing"
    elif heartbeat_age is not None and heartbeat_age < 0.0:
        process_status = "clock_skew"
    elif heartbeat_age is not None and heartbeat_age > process_threshold:
        process_status = "stale"
    else:
        process_status = "running"

    jobs: list[dict[str, Any]] = []
    stale_jobs: list[str] = []
    waiting_jobs: list[str] = []
    paused_jobs: list[str] = []
    failed_jobs: list[str] = []
    kill_switch_active: bool | None = None
    raw_jobs = state.get("jobs")
    if isinstance(raw_jobs, Mapping):
        for fallback_id, raw_job in raw_jobs.items():
            if not isinstance(raw_job, Mapping):
                continue
            job_id = str(raw_job.get("job_id") or fallback_id)
            status = str(raw_job.get("status") or "unknown")
            job_heartbeat = parse_datetime_safe(raw_job.get("heartbeat_at"))
            job_age = (current - job_heartbeat).total_seconds() if job_heartbeat is not None else None
            threshold = finite_number(raw_job.get("stale_after_seconds"))
            if threshold is None or threshold <= 0.0:
                threshold = default_job_threshold
            stale = status in _ACTIVE_JOB_STATES and (
                job_age is None or job_age < 0.0 or job_age > threshold
            )
            pause_reason = raw_job.get("pause_reason")
            if isinstance(pause_reason, str) and "kill_switch" in pause_reason.lower():
                kill_switch_active = True
            if stale:
                stale_jobs.append(job_id)
            if status == "waiting":
                waiting_jobs.append(job_id)
            elif status == "paused":
                paused_jobs.append(job_id)
            elif status == "failed":
                failed_jobs.append(job_id)
            stages = raw_job.get("stages")
            stage = raw_job.get("stage")
            stage_state = None
            if (
                isinstance(stages, Mapping)
                and isinstance(stage, str)
                and stage in stages
                and isinstance(stages[stage], Mapping)
            ):
                stage_state = dict(stages[stage])
            jobs.append({
                "job_id": job_id,
                "status": status,
                "stage": stage,
                "current_stage_state": stage_state,
                "scheduled_at": raw_job.get("scheduled_at"),
                "started_at": raw_job.get("started_at"),
                "heartbeat_at": raw_job.get("heartbeat_at"),
                "heartbeat_age_seconds": job_age,
                "completed_at": raw_job.get("completed_at"),
                "pause_reason": pause_reason,
                "stale": stale,
            })
    healthy = process_status == "running" and not stale_jobs and not failed_jobs
    return {
        "available": True,
        "process_status": process_status,
        "healthy": healthy,
        "process_id": process_id,
        "pid_alive": pid_alive,
        "pid_check_error": pid_check_error,
        "process_started_at": state.get("process_started_at"),
        "process_heartbeat_at": state.get("process_heartbeat_at"),
        "heartbeat_age_seconds": heartbeat_age,
        "stopped_at": state.get("stopped_at"),
        "stopped_cleanly": stopped_cleanly,
        "recovery_count": (
            int(state["recovery_count"])
            if isinstance(state.get("recovery_count"), int)
            and not isinstance(state.get("recovery_count"), bool)
            and state["recovery_count"] >= 0
            else None
        ),
        "kill_switch_active": kill_switch_active,
        "jobs": sorted(jobs, key=lambda row: row["job_id"]),
        "stale_jobs": tuple(sorted(stale_jobs)),
        "waiting_jobs": tuple(sorted(waiting_jobs)),
        "paused_jobs": tuple(sorted(paused_jobs)),
        "failed_jobs": tuple(sorted(failed_jobs)),
    }


# ── 전략 룰 재현 백테스트 (DB 저장 배분과 분리된 화면 내 계산) ──────────────
# Research 로컬 배분에는 운영이 실제로 적재한 달만 있다. 룰 자체는 월말 종가만
# 있으면 과거로도 재현되므로, 저장 이력이 닿지 않는 구간은 이 함수가 화면에서
# walk-forward로 만든다. 저장은 하지 않는다.
