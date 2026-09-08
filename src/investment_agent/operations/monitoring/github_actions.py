"""GitHub Actions 실행 이력 조회.

DB의 run_log가 아니라 Actions API를 본다. run_log는 파이프라인 다섯 곳에만 있고
(market·tech_indicators·universe·strategy는 없다), 무엇보다 **잡이 아예 안 뜬 경우**를
DB로는 볼 수 없다 — 워크플로 이름이 어긋나 workflow_run이 발화하지 않거나 파일명을
바꿔 새 ID가 발급된 날, DB에는 아무 흔적도 남지 않는다. 그게 실제로 카드를 며칠씩
빠뜨린 원인이었다.

주의: 이 저장소는 `/actions/runs`(전체 목록)가 404를 준다. 워크플로별 경로만 쓴다.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

_API = "https://api.github.com"
_TIMEOUT = 20


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY not set")
    return repo


def list_workflows() -> list[dict[str, Any]]:
    """`.github/workflows` 에 등록된 워크플로 목록(동적 워크플로는 제외)."""
    res = requests.get(
        f"{_API}/repos/{_repo()}/actions/workflows",
        headers=_headers(), params={"per_page": 100}, timeout=_TIMEOUT,
    )
    res.raise_for_status()
    return [
        wf for wf in res.json().get("workflows", [])
        if str(wf.get("path", "")).startswith(".github/workflows/")
    ]


def runs_since(workflow_id: int, since: datetime, *, limit: int = 30) -> list[dict[str, Any]]:
    """since(UTC) 이후에 생성된 실행만 최신순으로."""
    res = requests.get(
        f"{_API}/repos/{_repo()}/actions/workflows/{workflow_id}/runs",
        headers=_headers(), params={"per_page": limit}, timeout=_TIMEOUT,
    )
    res.raise_for_status()
    out = []
    for run in res.json().get("workflow_runs", []):
        created = datetime.fromisoformat(str(run["created_at"]).replace("Z", "+00:00"))
        if created >= since:
            out.append({
                "created_at": created,
                "event": run.get("event"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "url": run.get("html_url"),
            })
    return out


def jobs_for_run(run_id: int, *, attempt: int | None = None) -> list[dict[str, Any]]:
    """한 Actions 실행의 잡과 단계 결론을 반환한다."""
    if attempt is not None and attempt > 0:
        path = f"/repos/{_repo()}/actions/runs/{run_id}/attempts/{attempt}/jobs"
    else:
        path = f"/repos/{_repo()}/actions/runs/{run_id}/jobs"
    res = requests.get(
        _API + path,
        headers=_headers(),
        params={"filter": "latest", "per_page": 100},
        timeout=_TIMEOUT,
    )
    res.raise_for_status()
    return [dict(job) for job in res.json().get("jobs", [])]


def job_log(job_id: int) -> str:
    """원인 한 줄 추출용으로 잡 원문 로그를 내려받는다."""
    res = requests.get(
        f"{_API}/repos/{_repo()}/actions/jobs/{job_id}/logs",
        headers=_headers(),
        timeout=_TIMEOUT,
    )
    res.raise_for_status()
    return res.content.decode("utf-8", "replace")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
