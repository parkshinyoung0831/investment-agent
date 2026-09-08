"""GitHub Actions 실패 위치를 찾아 Discord 시스템 로그에 한 장으로 보낸다."""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

from investment_agent.operations.runtime import notify_ops
from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.operations.monitoring import github_actions as github
from investment_agent.operations.monitoring.incidents import (
    Incident,
    build_incident_embed,
    classify_incident,
    extract_error_summary,
    failed_job,
    failed_step,
)

log = get_logger(__name__)


def _integer(value: str, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _jobs(run_id: int, attempt: int) -> list[dict]:
    """Actions API의 짧은 반영 지연만 제한적으로 재시도한다."""
    last_error: Exception | None = None
    for delay in (0.0, 1.0, 2.0):
        if delay:
            time.sleep(delay)
        try:
            rows = github.jobs_for_run(run_id, attempt=attempt)
            if rows:
                return rows
        except Exception as exc:  # noqa: BLE001 - 위치 부가정보 없이도 알림은 보내야 한다
            last_error = exc
    if last_error is not None:
        log.warning("workflow failure jobs lookup failed: %s", last_error)
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.workflow_failure")
    parser.add_argument("--conclusion", default=os.getenv("SOURCE_CONCLUSION", "failure"))
    parser.add_argument("--workflow", default=os.getenv("GITHUB_WORKFLOW", "unknown"))
    parser.add_argument("--run-id", type=int, default=_integer(os.getenv("GITHUB_RUN_ID", "0"), default=0))
    parser.add_argument(
        "--run-attempt",
        type=int,
        default=_integer(os.getenv("GITHUB_RUN_ATTEMPT", "1"), default=1),
    )
    args = parser.parse_args(argv)
    configure_logging()

    url = (
        f"{os.getenv('GITHUB_SERVER_URL', 'https://github.com')}/"
        f"{os.getenv('GITHUB_REPOSITORY', '')}/actions/runs/{args.run_id}"
    )
    jobs = _jobs(args.run_id, args.run_attempt) if args.run_id > 0 else []
    job = failed_job(jobs, args.conclusion)
    job_name = str((job or {}).get("name") or "실패 잡 확인 필요")
    step_name = failed_step(job)
    fallback = (
        "GitHub Actions가 작업을 취소했어요."
        if args.conclusion in {"cancelled", "canceled", "timed_out"}
        else "실패 원인을 자동 요약하지 못했어요. 실행 링크에서 원문 로그를 확인해 주세요."
    )
    raw_log = ""
    if job and job.get("id"):
        try:
            raw_log = github.job_log(int(job["id"]))
        except Exception as exc:  # noqa: BLE001 - 로그 다운로드 실패가 알림을 막지 않는다
            log.warning("workflow failure job log lookup failed: %s", exc)
    summary = extract_error_summary(raw_log, fallback=fallback)
    category = classify_incident(args.conclusion, job_name, step_name, summary)
    incident = Incident(
        workflow=args.workflow,
        conclusion=args.conclusion,
        job=job_name,
        step=step_name,
        summary=summary,
        category=category,
        url=url,
        occurred_at=datetime.now(timezone.utc),
        event=os.getenv("GITHUB_EVENT_NAME", "unknown"),
        run_attempt=args.run_attempt,
        sha=os.getenv("GITHUB_SHA", ""),
    ).normalized()
    sent = notify_ops("", logger=log, embeds=[build_incident_embed(incident)])
    log.info(
        "workflow failure report: sent=%s incident_id=%s workflow=%s job=%s step=%s",
        sent,
        incident.identifier,
        incident.workflow,
        incident.job,
        incident.step,
    )
    # 리포터 실패가 원래 결론을 가리거나 재귀 알림을 만들면 안 된다. 원래 실패는
    # 호출 워크플로에 이미 남아 있고, 리포터 전달 여부는 일일 heartbeat가 감시한다.
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
