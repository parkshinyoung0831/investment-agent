"""Discord 시스템 로그에 보낼 운영 사건을 안전하게 구성한다.

원문 로그는 GitHub Actions가 보관한다. Discord에는 사람이 훑을 수 있는 실패 위치와
짧은 원인만 싣고, 토큰·웹훅·자격증명처럼 보이는 값은 전송 전에 다시 가린다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from investment_agent.operations.palette import STATUS_DANGER, STATUS_WARNING

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_LOG_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\S+Z\s+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(authorization|token|api[_-]?key|secret|password|passwd|webhook)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]{10,})?\b")
_WEBHOOK_RE = re.compile(r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\S+", re.I)
_URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@")
_MENTION_RE = re.compile(r"@(everyone|here|[!&]?\d+)", re.I)
_JSON_START_RE = re.compile(r"\{")
_ERROR_LINE_RE = re.compile(
    r"(?i)(traceback|exception|error|failed|failure|timeout|timed out|cancelled|"
    r"module not found|permission denied|rate.?limit|connection refused|pgrst\d+)"
)
_NOISE_RE = re.compile(
    r"(?i)^(##\[|\s*run\s+|\s*shell:|\s*env:|\s*with:|\s*post job cleanup|"
    r"\s*cleaning up orphan processes)"
)

_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cancelled", re.compile(r"(?i)cancelled|canceled")),
    ("timeout", re.compile(r"(?i)timeout|timed out|deadline exceeded|statement timeout")),
    ("configuration", re.compile(r"(?i)not set|missing secret|required secret|permission denied|forbidden|401|403")),
    ("dependency", re.compile(r"(?i)module not found|modulenotfounderror|no module named|pip.*failed|dependency")),
    ("database", re.compile(r"(?i)supabase|postgres|postgrest|pgrst\d+|sqlstate|database|relation .* does not exist")),
    ("provider", re.compile(r"(?i)rate.?limit|429|connection|dns|http|request|provider|edgar|fred|yahoo|openfigi")),
    ("data_contract", re.compile(r"(?i)integrity|contract|schema drift|validation|invalid|mismatch|quality")),
)

_KST = ZoneInfo("Asia/Seoul")

_ACTION_BY_CATEGORY = {
    "cancelled": "실행 링크에서 취소 원인과 동시 실행 상태를 확인한 뒤 필요하면 다시 실행해 주세요.",
    "timeout": "실행 링크에서 오래 걸린 단계를 확인하고 공급자 상태나 시간 제한을 점검해 주세요.",
    "configuration": "실행 링크의 실패 단계를 확인하고 Repository secret·권한·설정을 점검해 주세요.",
    "dependency": "실패 단계의 import·설치 로그를 확인하고 해당 requirements 파일을 고쳐 주세요.",
    "database": "Supabase 연결과 선언 스키마 배포 상태를 확인한 뒤 안전하게 다시 실행해 주세요.",
    "provider": "외부 공급자 상태와 요청 제한을 확인한 뒤 잠시 후 다시 실행해 주세요.",
    "data_contract": "실패한 검증 항목과 입력 데이터를 확인한 뒤 원인을 수정하고 다시 실행해 주세요.",
    "code": "실행 링크에서 실패 단계의 원문 로그를 확인하고 수정한 뒤 다시 실행해 주세요.",
}


def _clip(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def redact(text: object) -> str:
    """Discord로 보내기 전에 비밀값과 강제 mention을 제거한다."""
    value = _ANSI_RE.sub("", str(text or ""))
    value = _WEBHOOK_RE.sub("[가려진 Discord webhook]", value)
    value = _URL_CREDENTIAL_RE.sub(r"\1[가려진 자격증명]@", value)
    value = _BEARER_RE.sub("Bearer [가려진 토큰]", value)
    value = _JWT_RE.sub("[가려진 JWT]", value)
    value = _SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=[가려짐]", value)
    value = _MENTION_RE.sub(lambda m: "@\u200b" + m.group(1), value)
    return " ".join(value.replace("```", "'''" ).split())


def _json_error(line: str) -> str | None:
    match = _JSON_START_RE.search(line)
    if match is None:
        return None
    try:
        payload = json.loads(line[match.start() :])
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    level = str(payload.get("level") or "").upper()
    if level not in {"ERROR", "CRITICAL"} and not payload.get("exc"):
        return None
    parts = [payload.get("msg")]
    exc = payload.get("exc")
    if isinstance(exc, dict):
        parts.append(exc.get("type"))
        parts.append(exc.get("message"))
    elif exc:
        parts.append(exc)
    return ": ".join(str(part) for part in parts if part)


def extract_error_summary(log_text: str, *, fallback: str) -> str:
    """잡 로그 끝부분에서 가장 설명력 있는 오류 한 줄을 뽑는다."""
    candidates: list[str] = []
    lines = str(log_text or "").splitlines()[-800:]
    for raw in lines:
        line = _LOG_PREFIX_RE.sub("", _ANSI_RE.sub("", raw)).strip()
        if not line or _NOISE_RE.search(line):
            continue
        structured = _json_error(line)
        if structured:
            candidates.append(structured)
        elif _ERROR_LINE_RE.search(line):
            candidates.append(line)
    selected = candidates[-1] if candidates else fallback
    return _clip(redact(selected), 500) or fallback


def classify_incident(*values: object) -> str:
    combined = " ".join(str(value or "") for value in values)
    for category, pattern in _CATEGORY_RULES:
        if pattern.search(combined):
            return category
    return "code"


def _impact_for(workflow: str) -> str:
    lowered = workflow.lower()
    if lowered == "ci" or "test" in lowered:
        return "변경 사항의 자동 검증이 끝나지 않았어요. 배포 판단을 보류해 주세요."
    if lowered.startswith("notify_"):
        return "해당 Discord 알림이 예정대로 전달되지 않았을 수 있어요."
    if "heartbeat" in lowered:
        return "일일 시스템 상태 카드가 전달되지 않았을 수 있어요."
    if any(token in lowered for token in ("market", "macro", "fundamental", "universe", "guru", "econ", "strategy", "indicator")):
        return "관련 데이터나 계산 결과의 최신 갱신이 보류됐을 수 있어요."
    return "이 작업이 제공하는 결과가 최신 상태가 아닐 수 있어요."


def incident_id(workflow: str, job: str, step: str, category: str) -> str:
    seed = "|".join((workflow, job, step, category)).lower().encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()[:10]
    prefix = re.sub(r"[^a-z0-9_-]+", "-", workflow.lower()).strip("-") or "workflow"
    return f"{prefix}:{category}:{digest}"


@dataclass(frozen=True)
class Incident:
    """사람이 대응에 필요한 최소 운영 사건."""

    workflow: str
    conclusion: str
    job: str
    step: str
    summary: str
    category: str
    url: str
    occurred_at: datetime
    event: str = "unknown"
    run_attempt: int = 1
    sha: str = ""
    impact: str = ""
    action: str = ""
    identifier: str = ""

    def normalized(self) -> "Incident":
        category = self.category or classify_incident(self.conclusion, self.summary)
        return Incident(
            workflow=_clip(redact(self.workflow), 120) or "unknown",
            conclusion=_clip(redact(self.conclusion), 40) or "failure",
            job=_clip(redact(self.job), 160) or "확인 필요",
            step=_clip(redact(self.step), 160) or "확인 필요",
            summary=_clip(redact(self.summary), 500) or "원인을 자동 요약하지 못했어요.",
            category=category,
            url=str(self.url or ""),
            occurred_at=(self.occurred_at if self.occurred_at.tzinfo else self.occurred_at.replace(tzinfo=timezone.utc)),
            event=_clip(redact(self.event), 60) or "unknown",
            run_attempt=max(1, int(self.run_attempt or 1)),
            sha=_clip(redact(self.sha), 40),
            impact=_clip(redact(self.impact or _impact_for(self.workflow)), 500),
            action=_clip(redact(self.action or _ACTION_BY_CATEGORY.get(category, _ACTION_BY_CATEGORY["code"])), 500),
            identifier=self.identifier or incident_id(self.workflow, self.job, self.step, category),
        )


def build_incident_embed(incident: Incident) -> dict[str, Any]:
    """Discord Navigating Error 순서의 embed payload를 만든다."""
    item = incident.normalized()
    stopped = item.conclusion in {"cancelled", "canceled", "timed_out"}
    partial = item.conclusion in {"partial", "warning"}
    title = (
        "자동화 작업이 중단됐어요"
        if stopped
        else "일부 자동화 결과를 확인해 주세요"
        if partial
        else "자동화 작업에 문제가 생겼어요"
    )
    status = "중단" if stopped else "부분 실패" if partial else "실패"
    location = f"{item.workflow} / {item.job} / {item.step}"
    run_meta = f"{item.event} · 시도 {item.run_attempt}"
    if item.sha:
        run_meta += f" · {item.sha[:7]}"
    embed: dict[str, Any] = {
        "title": title,
        "description": "원문 로그는 GitHub Actions에 두고, 대응에 필요한 내용만 정리했어요.",
        "color": STATUS_WARNING if stopped or partial else STATUS_DANGER,
        "fields": [
            {"name": "상태", "value": status, "inline": True},
            {"name": "분류", "value": item.category, "inline": True},
            {"name": "실패 위치", "value": _clip(location, 1024), "inline": False},
            {"name": "원인", "value": item.summary, "inline": False},
            {"name": "영향", "value": item.impact, "inline": False},
            {"name": "다음 행동", "value": item.action, "inline": False},
            {
                "name": "발생 시각",
                "value": item.occurred_at.astimezone(_KST).strftime("%Y-%m-%d %H:%M:%S KST"),
                "inline": False,
            },
            {"name": "실행 정보", "value": run_meta, "inline": False},
        ],
        "footer": {"text": f"사건 ID · {item.identifier}"},
        "timestamp": item.occurred_at.astimezone(timezone.utc).isoformat(),
    }
    if item.url.startswith("https://"):
        embed["url"] = item.url
    return embed


def build_runtime_incident(
    *,
    workflow: str,
    step: str,
    summary: str,
    conclusion: str = "failure",
    impact: str = "",
    action: str = "",
    url: str = "",
    occurred_at: datetime | None = None,
) -> Incident:
    """파이프라인 내부의 부분 실패도 같은 카드 계약으로 바꾼다."""
    category = classify_incident(conclusion, step, summary)
    return Incident(
        workflow=workflow,
        conclusion=conclusion,
        job="application",
        step=step,
        summary=summary,
        category=category,
        impact=impact,
        action=action,
        url=url,
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )


def current_github_run_url() -> str:
    """현재 실행 링크를 만들되 로컬 실행이면 빈 문자열을 반환한다."""
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    if not repository or not run_id:
        return ""
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    return f"{server}/{repository}/actions/runs/{run_id}"


def failed_job(jobs: Iterable[dict[str, Any]], conclusion: str) -> dict[str, Any] | None:
    """리포터 자신을 제외하고 원래 실패/중단 잡을 고른다."""
    rows = [
        dict(job)
        for job in jobs
        if "ops_failure_report" not in str(job.get("name") or "").lower()
        and "discord failure report" not in str(job.get("name") or "").lower()
    ]
    wanted = [job for job in rows if str(job.get("conclusion") or "") == conclusion]
    if not wanted and conclusion in {"cancelled", "canceled", "timed_out"}:
        wanted = [
            job for job in rows
            if str(job.get("conclusion") or "") in {"cancelled", "canceled", "timed_out"}
        ]
    if not wanted:
        wanted = [job for job in rows if str(job.get("conclusion") or "") not in {"", "success", "skipped"}]
    return wanted[-1] if wanted else None


def failed_step(job: dict[str, Any] | None) -> str:
    if not job:
        return "실패 단계 확인 필요"
    steps = [
        step for step in (job.get("steps") or [])
        if str(step.get("conclusion") or "") in {"failure", "cancelled", "canceled", "timed_out"}
    ]
    return str(steps[-1].get("name") or "실패 단계 확인 필요") if steps else "잡 실행"


__all__ = [
    "Incident",
    "build_incident_embed",
    "build_runtime_incident",
    "classify_incident",
    "current_github_run_url",
    "extract_error_summary",
    "failed_job",
    "failed_step",
    "incident_id",
    "redact",
]
