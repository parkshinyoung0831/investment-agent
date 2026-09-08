"""저장 형태와 무관하게 투자 판단을 작은 화면용 계약으로 정규화한다."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from investment_agent.platform.serialization import parse_datetime

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bounded_text(value: Any, *, limit: int) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _bounded_texts(values: Any, *, count: int = 50, length: int = 500) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    output = []
    for value in values:
        text = _bounded_text(value, limit=length)
        if text is not None:
            output.append(text)
        if len(output) >= count:
            break
    return output


def _role_entry(role: str, payload: Any) -> dict[str, Any] | None:
    """실제 내용이 있는 역할 분석 하나만 read model 후보로 정규화한다."""

    normalized_role = str(role or "").strip()
    if not normalized_role or payload is None:
        return None
    if isinstance(payload, str):
        summary = payload.strip()
        return {"role": normalized_role, "summary": summary} if summary else None
    if not isinstance(payload, Mapping) or not payload:
        return None
    entry = dict(payload)
    entry["role"] = str(entry.get("role") or normalized_role).strip()
    if not entry["role"]:
        return None
    meaningful = [
        value
        for key, value in entry.items()
        if key != "role" and value not in (None, "", [], {})
    ]
    return entry if meaningful else None


def normalize_role_analyses(value: Any) -> list[dict[str, Any]]:
    """저장 경로별 list/dict 역할 분석에서 실제 존재하는 역할만 평탄화한다."""

    output: list[dict[str, Any]] = []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            entry = _role_entry(str(item.get("role") or ""), item)
            if entry is not None:
                output.append(entry)
        return output
    if not isinstance(value, Mapping) or not value:
        return []
    if value.get("role"):
        entry = _role_entry(str(value["role"]), value)
        return [entry] if entry is not None else []

    report_roles = {
        "market_report": "market_analyst",
        "sentiment_report": "social_analyst",
        "news_report": "news_analyst",
        "fundamentals_report": "fundamental_analyst",
        "investment_plan": "research_manager",
        "trader_investment_plan": "trader",
        "final_trade_decision": "portfolio_manager",
    }
    for key, role in report_roles.items():
        entry = _role_entry(role, value.get(key))
        if entry is not None:
            output.append(entry)

    investment_debate = value.get("investment_debate_state")
    if isinstance(investment_debate, Mapping):
        for key, role in (
            ("bull_history", "bull"),
            ("bear_history", "bear"),
            ("judge_decision", "research_manager"),
        ):
            entry = _role_entry(role, investment_debate.get(key))
            if entry is not None:
                output.append(entry)
    risk_debate = value.get("risk_debate_state")
    if isinstance(risk_debate, Mapping):
        for key, role in (
            ("risky_history", "risk_manager_aggressive"),
            ("safe_history", "risk_manager_conservative"),
            ("neutral_history", "risk_manager_neutral"),
            ("judge_decision", "risk_manager"),
        ):
            entry = _role_entry(role, risk_debate.get(key))
            if entry is not None:
                output.append(entry)

    known = set(report_roles) | {"investment_debate_state", "risk_debate_state"}
    for role, payload in value.items():
        if role in known:
            continue
        entry = _role_entry(str(role), payload)
        if entry is not None:
            output.append(entry)
    return output


def _claim_summaries(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    output: list[dict[str, Any]] = []
    for value in values[:20]:
        if isinstance(value, Mapping):
            text = _bounded_text(value.get("text"), limit=500)
            if text is None:
                continue
            output.append({
                "text": text,
                "evidence_ids": _bounded_texts(
                    value.get("evidence_ids"), count=50, length=200
                ),
            })
        else:
            text = _bounded_text(value, limit=500)
            if text is not None:
                output.append({"text": text, "evidence_ids": []})
    return output


def summarize_role_analyses(value: Any) -> list[dict[str, Any]]:
    """role 원문의 화면 사용 필드만 길이와 개수를 제한해 남긴다."""

    output: list[dict[str, Any]] = []
    for entry in normalize_role_analyses(value)[:50]:
        summary = (
            _bounded_text(entry.get("summary"), limit=2000)
            or _bounded_text(entry.get("text"), limit=2000)
            or _bounded_text(entry.get("content"), limit=2000)
        )
        row: dict[str, Any] = {
            "role": _bounded_text(entry.get("role"), limit=100) or "저장된 분석",
        }
        if summary is not None:
            row["summary"] = summary
        stance = _bounded_text(entry.get("stance"), limit=50)
        if stance is not None:
            row["stance"] = stance
        confidence = entry.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            row["confidence"] = float(confidence)
        claims = _claim_summaries(entry.get("claims"))
        if claims:
            row["claims"] = claims
        risks = _bounded_texts(entry.get("risks"), count=20, length=500)
        if risks:
            row["risks"] = risks
        missing = _bounded_texts(entry.get("missing_data"), count=20, length=500)
        if missing:
            row["missing_data"] = missing
        output.append(row)
    return output


def _newer(current: str | None, candidate: Any) -> str | None:
    if candidate in (None, ""):
        return current
    try:
        normalized = parse_datetime(str(candidate)).isoformat()
    except (TypeError, ValueError):
        return current
    if current is None or parse_datetime(normalized) > parse_datetime(current):
        return normalized
    return current


def _bounded_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    output: dict[str, int] = {}
    for key, count in list(value.items())[:100]:
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            output[str(key)[:200]] = count
    return dict(sorted(output.items()))


def _bounded_timestamps(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    output: dict[str, str] = {}
    for key, timestamp in list(value.items())[:100]:
        normalized = _newer(None, timestamp)
        if normalized is not None:
            output[str(key)[:100]] = normalized
    return dict(sorted(output.items()))


def _normalize_digest(value: Any) -> dict[str, Any]:
    source = _mapping(value)
    if not source:
        return {}
    evidence_count = source.get("evidence_count")
    role_count = source.get("role_analysis_count")
    return {
        "ticker": _bounded_text(source.get("ticker"), limit=15) or "",
        "as_of_at": _bounded_text(source.get("as_of_at"), limit=100),
        "source_kind": _bounded_text(source.get("source_kind"), limit=50),
        "evidence_count": (
            evidence_count
            if isinstance(evidence_count, int)
            and not isinstance(evidence_count, bool)
            and evidence_count >= 0
            else 0
        ),
        "domain_counts": _bounded_counts(source.get("domain_counts")),
        "source_counts": _bounded_counts(source.get("source_counts")),
        "latest_available_at": _bounded_timestamps(source.get("latest_available_at")),
        "latest_filed_at": _bounded_timestamps(source.get("latest_filed_at")),
        "external_evidence_ids": _bounded_texts(
            source.get("external_evidence_ids"), count=100, length=200
        ),
        "missing_data": _bounded_texts(source.get("missing_data")),
        "warnings": _bounded_texts(source.get("warnings")),
        "role_analysis_count": (
            role_count
            if isinstance(role_count, int)
            and not isinstance(role_count, bool)
            and role_count >= 0
            else 0
        ),
    }


def _normalize_manifest(value: Any) -> dict[str, Any]:
    source = _mapping(value)
    sha256 = str(source.get("sha256") or "").strip().lower()
    uri = str(source.get("uri") or "").strip()
    if not _SHA256_RE.fullmatch(sha256) or not uri.startswith("artifact://"):
        return {}
    schema_version = source.get("schema_version")
    if isinstance(schema_version, str) and schema_version.isdigit():
        schema_version = int(schema_version)
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 0
    ):
        schema_version = None
    byte_size = source.get("byte_size")
    if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0:
        byte_size = None
    return {
        "artifact_id": _bounded_text(source.get("artifact_id"), limit=200),
        "artifact_kind": _bounded_text(source.get("artifact_kind"), limit=100),
        "sha256": sha256,
        "uri": uri[:1000],
        "code_commit": _bounded_text(source.get("code_commit"), limit=200),
        "schema_version": schema_version,
        "created_at": _bounded_text(source.get("created_at"), limit=100),
        "byte_size": byte_size,
    }


def build_decision_case_read_model(row: Mapping[str, Any]) -> dict[str, Any]:
    """현재 reporting view 행을 bounded 화면 계약으로 정규화한다."""

    output = dict(row)
    final_decision = _mapping(output.get("final_decision"))
    raw_digest = output.get("evidence_digest") or final_decision.get("evidence_digest")
    digest = _normalize_digest(raw_digest)
    raw_manifest = output.get("evidence_manifest")
    if not isinstance(raw_manifest, Mapping) and output.get("evidence_uri"):
        raw_manifest = {
            "artifact_kind": "decision_evidence",
            "sha256": output.get("evidence_sha256"),
            "uri": output.get("evidence_uri"),
            "schema_version": output.get("evidence_schema_version"),
            "byte_size": output.get("evidence_byte_size"),
        }
    manifest = _normalize_manifest(raw_manifest)
    artifact_error = _bounded_text(
        output.get("evidence_artifact_error") or final_decision.get("evidence_artifact_error"),
        limit=500,
    )
    if manifest:
        storage = "artifact"
    elif artifact_error:
        storage = "artifact_error"
    else:
        storage = "missing"

    output.update({
        "evidence_digest": digest,
        "evidence_manifest": manifest,
        "evidence_artifact_error": artifact_error,
        "evidence_storage": storage,
        "evidence_items": [],
        "role_summaries": [],
    })
    return output


def build_decision_cases_read_model(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """결정 행 목록을 순서 변경 없이 bounded read model로 변환한다."""

    return [build_decision_case_read_model(row) for row in rows]


__all__ = [
    "build_decision_case_read_model",
    "build_decision_cases_read_model",
    "normalize_role_analyses",
    "summarize_role_analyses",
]
