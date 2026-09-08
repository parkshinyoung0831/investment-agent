"""판단 근거와 역할 분석 원문을 DB 밖의 content-addressed artifact로 보관한다."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from investment_agent.platform.serialization import canonical_json, json_value, parse_datetime

ARTIFACT_KIND = "decision_evidence"
ARTIFACT_SCHEMA_VERSION = 1
DEFAULT_ARTIFACT_ROOT = Path("artifacts/ai_investor/tradingagents")
_ARTIFACT_URI_PREFIX = "artifact://"


class EvidenceArtifactError(RuntimeError):
    """근거 artifact를 완전하게 기록하거나 검증할 수 없을 때 발생한다."""


@dataclass(frozen=True)
class EvidenceArtifactManifest:
    """DB와 artifact 파일을 결박하는 작은 불변 manifest."""

    artifact_id: str
    artifact_kind: str
    sha256: str
    uri: str
    code_commit: str | None
    schema_version: int
    created_at: str
    byte_size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArchivedCaseEvidence:
    """artifact 기록 뒤 DB에 남길 메타데이터와 검증 결과."""

    evidence_bundle: dict[str, Any]
    role_analyses: Any
    manifest: EvidenceArtifactManifest | None
    digest: dict[str, Any]
    artifact_error: str | None = None


def _bounded_texts(values: Any, *, limit: int = 50) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value).strip()[:500] for value in values if str(value).strip()][:limit]


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


def _latest_timestamp(value: Any, keys: frozenset[str]) -> str | None:
    latest: str | None = None
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, Mapping):
            for key, child in item.items():
                if str(key) in keys:
                    latest = _newer(latest, child)
                elif isinstance(child, (Mapping, list, tuple)):
                    stack.append(child)
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return latest


def build_evidence_digest(
    evidence_bundle: Mapping[str, Any],
    role_analyses: Any,
) -> dict[str, Any]:
    """화면·감사에 필요한 최소 요약만 만들고 원문 payload는 포함하지 않는다."""

    evidence = evidence_bundle.get("evidence")
    rows = evidence if isinstance(evidence, list) else []
    domain_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    latest_available_at: dict[str, str] = {}
    latest_filed_at: dict[str, str] = {}

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        domain = str(row.get("domain") or "unknown")[:100]
        source = str(row.get("source") or "unknown")[:200]
        domain_counts[domain] += 1
        source_counts[source] += 1
        available = _newer(latest_available_at.get(domain), row.get("available_at"))
        if available is not None:
            latest_available_at[domain] = available
        filed = _latest_timestamp(
            row.get("payload"), frozenset({"filed_at", "accepted_at"})
        )
        if filed is not None:
            latest_filed_at[domain] = _newer(latest_filed_at.get(domain), filed) or filed

    external_ids = sorted(
        {
            str(item.get("manifest_id"))
            for item in evidence_bundle.get("external_evidence", [])
            if isinstance(item, Mapping) and str(item.get("manifest_id") or "").strip()
        }
    )
    role_count = len(role_analyses) if isinstance(role_analyses, (list, tuple, Mapping)) else 0
    return {
        "ticker": str(evidence_bundle.get("ticker") or ""),
        "as_of_at": evidence_bundle.get("as_of_at"),
        "source_kind": evidence_bundle.get("source_kind"),
        "evidence_count": sum(domain_counts.values()),
        "domain_counts": dict(sorted(domain_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "latest_available_at": dict(sorted(latest_available_at.items())),
        "latest_filed_at": dict(sorted(latest_filed_at.items())),
        "external_evidence_ids": external_ids[:100],
        "missing_data": _bounded_texts(evidence_bundle.get("missing_data")),
        "warnings": _bounded_texts(evidence_bundle.get("warnings")),
        "role_analysis_count": role_count,
    }


class EvidenceArtifactStore:
    """결정 근거를 해시 경로에 원자적으로 기록하고 읽을 때 다시 검증한다."""

    def __init__(self, root: str | Path | None = None) -> None:
        configured = root
        if configured is None:
            configured = os.environ.get("AI_INVESTOR_ARTIFACT_DIR", str(DEFAULT_ARTIFACT_ROOT))
        if not str(configured).strip():
            raise EvidenceArtifactError("AI_INVESTOR_ARTIFACT_DIR must not be empty")
        self.root = Path(configured).expanduser()

    @staticmethod
    def _payload(
        *,
        case_key: str,
        evidence_bundle: Mapping[str, Any],
        role_analyses: Any,
    ) -> dict[str, Any]:
        if not str(case_key).strip():
            raise EvidenceArtifactError("case_key is required")
        return {
            "artifact_kind": ARTIFACT_KIND,
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "case_key": str(case_key),
            "evidence_bundle": json_value(dict(evidence_bundle)),
            "role_analyses": json_value(role_analyses),
        }

    def write_case(
        self,
        *,
        case_key: str,
        evidence_bundle: Mapping[str, Any],
        role_analyses: Any,
        code_commit: str | None = None,
    ) -> EvidenceArtifactManifest:
        payload = self._payload(
            case_key=case_key,
            evidence_bundle=evidence_bundle,
            role_analyses=role_analyses,
        )
        raw = canonical_json(payload).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        relative = Path("decision-evidence") / digest[:2] / f"{digest}.json"
        target = self.root / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                existing = target.read_bytes()
                if existing != raw or hashlib.sha256(existing).hexdigest() != digest:
                    raise EvidenceArtifactError(f"artifact hash collision or corruption: {relative}")
            else:
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{digest}.", suffix=".tmp", dir=target.parent
                )
                temporary = Path(temporary_name)
                try:
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(raw)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        except EvidenceArtifactError:
            raise
        except OSError as exc:
            raise EvidenceArtifactError(
                f"decision evidence artifact write failed: {type(exc).__name__}: {exc}"
            ) from exc

        created_at = datetime.fromtimestamp(target.stat().st_mtime, timezone.utc).isoformat()
        return EvidenceArtifactManifest(
            artifact_id=f"decision-evidence-{digest[:24]}",
            artifact_kind=ARTIFACT_KIND,
            sha256=digest,
            uri=_ARTIFACT_URI_PREFIX + relative.as_posix(),
            code_commit=(code_commit or os.environ.get("GITHUB_SHA") or None),
            schema_version=ARTIFACT_SCHEMA_VERSION,
            created_at=created_at,
            byte_size=len(raw),
        )

    def read(self, manifest: EvidenceArtifactManifest) -> dict[str, Any]:
        if not manifest.uri.startswith(_ARTIFACT_URI_PREFIX):
            raise EvidenceArtifactError("unsupported artifact URI")
        relative = Path(manifest.uri.removeprefix(_ARTIFACT_URI_PREFIX))
        if relative.is_absolute() or ".." in relative.parts:
            raise EvidenceArtifactError("artifact URI escapes configured root")
        try:
            raw = (self.root / relative).read_bytes()
        except OSError as exc:
            raise EvidenceArtifactError(f"artifact read failed: {type(exc).__name__}: {exc}") from exc
        actual = hashlib.sha256(raw).hexdigest()
        if actual != manifest.sha256 or len(raw) != manifest.byte_size:
            raise EvidenceArtifactError("artifact hash or size does not match manifest")
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("artifact_kind") != ARTIFACT_KIND:
            raise EvidenceArtifactError("unexpected artifact kind")
        return payload


def archive_case_evidence(
    *,
    case_key: str,
    evidence_bundle: Mapping[str, Any],
    role_analyses: Any,
    store: EvidenceArtifactStore | None = None,
    code_commit: str | None = None,
) -> ArchivedCaseEvidence:
    """artifact를 먼저 쓰고 DB에는 manifest와 digest만 남긴다."""

    raw_bundle = json_value(dict(evidence_bundle))
    raw_roles = json_value(role_analyses)
    digest = build_evidence_digest(raw_bundle, raw_roles)
    selected_store = store or EvidenceArtifactStore()
    try:
        manifest = selected_store.write_case(
            case_key=case_key,
            evidence_bundle=raw_bundle,
            role_analyses=raw_roles,
            code_commit=code_commit,
        )
    except EvidenceArtifactError as exc:
        error = f"{type(exc).__name__}: {exc}"[:500]
        return ArchivedCaseEvidence(
            evidence_bundle={"_digest": digest, "_artifact_error": error},
            role_analyses=[],
            manifest=None,
            digest=digest,
            artifact_error=error,
        )

    return ArchivedCaseEvidence(
        evidence_bundle={
            "_artifact": manifest.to_dict(),
            "_digest": digest,
        },
        role_analyses=[],
        manifest=manifest,
        digest=digest,
    )


__all__ = [
    "ARTIFACT_KIND",
    "ARTIFACT_SCHEMA_VERSION",
    "ArchivedCaseEvidence",
    "EvidenceArtifactError",
    "EvidenceArtifactManifest",
    "EvidenceArtifactStore",
    "archive_case_evidence",
    "build_evidence_digest",
]
