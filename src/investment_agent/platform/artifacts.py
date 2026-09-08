"""큰 산출물을 DB 밖에 두고, DB에는 주소와 지문만 남긴다.

## 왜 DB에서 뺐나

판단 근거 번들은 한 건에 수십 KB다. 그것을 `jsonb` 컬럼에 넣었더니 두 가지가 생겼다.

  1. 표 하나가 DB 용량의 큰 몫을 먹었다. 무료 한도(500MB)는 생각보다 빨리 온다.
  2. 화면이 목록을 그릴 때 근거 payload까지 함께 실려 왔다. 쓰지도 않는 수십 KB가
     행마다 붙으면 PostgREST의 8초 제한에 닿는다.

그래서 내용은 파일로 내보내고, DB에는 **주소·지문·크기**만 남긴다.

## 왜 내용 주소(content-addressed)인가

파일 이름이 sha256이면 같은 내용은 항상 같은 자리에 놓인다. 덕분에 두 번 저장해도
파일이 하나고, 읽을 때 지문을 다시 계산해 **파일이 바뀌었는지 확인**할 수 있다.
근거는 나중에 "그때 무엇을 보고 판단했나"에 답하는 물건이라, 조용히 바뀌면 그
답 자체가 거짓이 된다.

## URI에 파일 경로를 적지 않는다

`local://<namespace>/<sha256>` 형태로 적는다. 실제 위치는 store가 안다. 절대경로를
DB에 적으면 저장 위치를 옮기는 순간 과거 행이 전부 깨지고, 그 행들은 고칠 수 없다.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from investment_agent.platform.serialization import canonical_json

SCHEME = "local"


class StorageError(RuntimeError):
    """저장물을 읽을 수 없거나 지문이 맞지 않는다."""


@dataclass(frozen=True)
class ArtifactRef:
    """DB에 적는 것 전부. 내용은 여기 없다."""

    uri: str
    sha256: str
    byte_size: int
    media_type: str = "application/json"

    def as_row(self) -> dict[str, Any]:
        """`trading.decision_evidence`가 받는 모양."""
        return {
            "artifact_uri": self.uri,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
        }


class ArtifactStore(Protocol):
    """저장 백엔드. 지금은 로컬 파일뿐이지만, 나중에 객체 저장소로 바꿔도 DB에 적힌
    URI는 그대로여야 한다."""

    def put_bytes(self, namespace: str, payload: bytes, *, media_type: str) -> ArtifactRef:
        ...  # pragma: no cover - Protocol 선언

    def get_bytes(self, ref: ArtifactRef) -> bytes:
        ...  # pragma: no cover - Protocol 선언


class LocalArtifactStore:
    """작업 트리 밖의 디렉터리에 내용 주소로 쌓는다."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def put_bytes(self, namespace: str, payload: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        digest = hashlib.sha256(payload).hexdigest()
        path = self._path(namespace, digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomically(path, payload)
        return ArtifactRef(
            uri=f"{SCHEME}://{namespace}/{digest}",
            sha256=digest,
            byte_size=len(payload),
            media_type=media_type,
        )

    def put_json(self, namespace: str, value: Any) -> ArtifactRef:
        """canonical JSON으로 저장한다 — 같은 내용이 항상 같은 지문을 갖도록."""
        return self.put_bytes(
            namespace,
            canonical_json(value).encode("utf-8"),
            media_type="application/json",
        )

    def get_bytes(self, ref: ArtifactRef) -> bytes:
        namespace, digest = _parse_uri(ref.uri)
        path = self._path(namespace, digest)
        if not path.exists():
            raise StorageError(f"artifact is missing: {ref.uri}")
        payload = path.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != ref.sha256:
            # 여기서 조용히 넘어가면 "그때 본 근거"가 아닌 것을 근거라고 부르게 된다.
            raise StorageError(f"artifact digest mismatch: {ref.uri}")
        return payload

    def get_json(self, ref: ArtifactRef) -> Any:
        import json

        return json.loads(self.get_bytes(ref).decode("utf-8"))

    def _path(self, namespace: str, digest: str) -> Path:
        _check_namespace(namespace)
        _check_digest(digest)
        # 앞 두 자리로 갈라 한 디렉터리에 파일이 수만 개 쌓이지 않게 한다.
        return self._root / namespace / digest[:2] / digest


def _write_atomically(path: Path, payload: bytes) -> None:
    """같은 디렉터리에 임시 파일로 쓴 뒤 rename. 중간에 죽어도 반쪽 파일이 남지 않는다.

    반쪽 파일이 남으면 지문이 맞지 않아 읽기가 실패하는데, 그 실패는 원인이
    "저장 중 중단"이라는 것을 말해주지 않는다.
    """
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _check_namespace(namespace: str) -> None:
    # 경로 조작을 막는다. namespace는 코드가 정하는 값이지만, 언젠가 데이터에서
    # 올 수 있고 그때 `../`가 통하면 저장소 밖을 쓴다.
    if not namespace or not all(part.isalnum() or part in "_-" for part in namespace):
        raise StorageError(f"invalid namespace: {namespace!r}")


def _check_digest(digest: str) -> None:
    if len(digest) != 64 or not all(char in "0123456789abcdef" for char in digest):
        raise StorageError(f"invalid sha256: {digest!r}")


def _parse_uri(uri: str) -> tuple[str, str]:
    prefix = f"{SCHEME}://"
    if not uri.startswith(prefix):
        raise StorageError(f"unsupported artifact uri: {uri!r}")
    namespace, _, digest = uri[len(prefix):].partition("/")
    _check_namespace(namespace)
    _check_digest(digest)
    return namespace, digest


__all__ = ["ArtifactRef", "ArtifactStore", "LocalArtifactStore", "SCHEME", "StorageError"]
