"""판단 근거를 파일로 내보내고 DB에는 주소만 남긴다.

## 왜 DB에 넣지 않는가

근거 번들은 한 건에 수십 KB다. `jsonb`에 넣었더니 그 표 하나가 무료 한도(500MB)의
큰 몫을 먹었고, 화면이 목록을 그릴 때 쓰지도 않는 payload가 행마다 함께 실려 왔다.

## 근거는 나중에 답해야 하는 물건이다

"그때 무엇을 보고 그렇게 판단했나"에 답하는 것이 근거의 존재 이유다. 그러므로 조용히
바뀌면 안 된다 — `sha256`을 함께 저장해, 읽을 때 그 파일이 그때 그 근거인지 확인한다.

## 두 종류를 나눠 저장한다

* `bundle` — 판단에 들어간 자료 전체.
* `role_analyses` — 각 역할(분석가)의 의견.

한 파일로 합치면 목록 화면이 역할 의견까지 통째로 받아 read model이 불필요하게 커진다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from investment_agent.platform.artifacts import ArtifactRef, LocalArtifactStore

EVIDENCE_KINDS = ("bundle", "role_analyses")

# 근거 스키마 버전. payload 모양이 바뀌면 증가시킨다.
SCHEMA_VERSION = "1"

# 저장소 namespace. 판단 근거만 여기 쌓인다.
NAMESPACE = "decision_evidence"


class EvidenceError(ValueError):
    """근거가 계약을 어겼다."""


@dataclass(frozen=True)
class StoredEvidence:
    """DB에 적을 것 전부. 내용은 여기 없다."""

    case_key: str
    evidence_kind: str
    ref: ArtifactRef

    def as_row(self) -> dict[str, Any]:
        return {
            "case_key": self.case_key,
            "evidence_kind": self.evidence_kind,
            "schema_version": SCHEMA_VERSION,
            **self.ref.as_row(),
        }


def store(
    store_backend: LocalArtifactStore,
    *,
    case_key: str,
    evidence_kind: str,
    payload: Mapping[str, Any],
) -> StoredEvidence:
    """근거를 파일로 내보내고 주소를 돌려준다."""
    if evidence_kind not in EVIDENCE_KINDS:
        raise EvidenceError(f"unknown evidence_kind: {evidence_kind!r}")
    if not payload:
        # 빈 근거를 저장하면 "근거가 있다"고 기록되면서 실제로는 없다.
        raise EvidenceError(f"{case_key}: {evidence_kind} payload is empty")
    ref = store_backend.put_json(NAMESPACE, dict(payload))
    return StoredEvidence(case_key=case_key, evidence_kind=evidence_kind, ref=ref)


def load(store_backend: LocalArtifactStore, row: Mapping[str, Any]) -> Any:
    """저장된 근거를 되읽는다. 지문이 다르면 예외 — 조용히 다른 근거를 주지 않는다."""
    ref = ArtifactRef(
        uri=str(row["artifact_uri"]),
        sha256=str(row["sha256"]),
        byte_size=int(row["byte_size"]),
    )
    version = str(row.get("schema_version") or "")
    if version != SCHEMA_VERSION:
        # 세대가 다른 근거를 지금 규칙으로 읽으면 필드가 조용히 비거나 뜻이 달라진다.
        raise EvidenceError(
            f"evidence schema {version!r} does not match {SCHEMA_VERSION!r}; "
            "read it with the reader of its own generation"
        )
    return store_backend.get_json(ref)


__all__ = [
    "EVIDENCE_KINDS",
    "EvidenceError",
    "NAMESPACE",
    "SCHEMA_VERSION",
    "StoredEvidence",
    "load",
    "store",
]
