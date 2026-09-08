"""뉴스·소셜 원문을 Supabase 밖의 재생성 가능한 DuckDB에 보관한다."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from investment_agent.trading.contracts import parse_datetime
from investment_agent.platform.serialization import canonical_json

from investment_agent.platform.storage_paths import evidence_cache_path
DEFAULT_RETENTION_DAYS = 90
_TRACKING_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "source"})
_CONTENT_TYPES = {"news", "social"}


class LocalEvidenceCacheError(RuntimeError):
    """로컬 외부 근거 캐시를 안전하게 사용할 수 없는 경우다."""


from investment_agent.platform.serialization import canonicalize_url


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _normalized_content(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def request_hash(*, domain: str, provider: str, request: Mapping[str, Any]) -> str:
    return _sha(canonical_json({"domain": domain, "provider": provider, "request": dict(request)}))


@dataclass(frozen=True)
class ExternalContent:
    """provider별 응답을 DuckDB가 공유하는 최소 계약으로 정규화한다."""

    provider: str
    content_type: str
    symbol: str | None
    published_at: str | None
    fetched_at: str
    url: str | None
    title: str | None
    content: str
    author: str | None = None
    source: str | None = None
    language: str | None = None
    relevance: float | None = None
    sentiment: float | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.content_type not in _CONTENT_TYPES:
            raise ValueError("content_type must be news or social")
        if not str(self.provider).strip() or not _normalized_content(self.content):
            raise ValueError("provider and non-empty content are required")
        fetched = parse_datetime(self.fetched_at)
        if fetched > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("fetched_at cannot be materially in the future")
        if self.published_at is not None and parse_datetime(self.published_at) > fetched:
            raise ValueError("published_at cannot be after fetched_at")

    def row(self) -> dict[str, Any]:
        canonical_url = canonicalize_url(self.url)
        normalized = _normalized_content(self.content)
        content_sha = _sha(normalized)
        url_sha = _sha(canonical_url) if canonical_url else _sha("no-url")
        identity = _sha(f"{url_sha}:{content_sha}")
        return {
            **asdict(self),
            "item_id": f"external_{identity[:24]}",
            "symbol": str(self.symbol).upper().strip() if self.symbol else None,
            "canonical_url": canonical_url,
            "url_hash": url_sha,
            "content_hash": content_sha,
            "first_seen_at": self.fetched_at,
            "metadata": canonical_json(dict(self.metadata or {})),
        }


class LocalEvidenceCache:
    """작은 local cache다. 손상 시 파일을 지우고 provider에서 재생성할 수 있다."""

    def __init__(self, path: str | Path | None = None, *, retention_days: int = DEFAULT_RETENTION_DAYS):
        # 경로는 호출 시점에 정한다. import 시점에 굳히면 테스트나 하네스가
        # 나중에 env를 바꿔도 옛 자리를 계속 본다.
        configured = path or evidence_cache_path()
        self.path = Path(configured).expanduser()
        if isinstance(retention_days, bool) or not 1 <= int(retention_days) <= 3650:
            raise ValueError("retention_days must be between 1 and 3650")
        self.retention_days = int(retention_days)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @staticmethod
    def _duckdb():
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - 설치 경계
            raise LocalEvidenceCacheError(
                "DuckDB가 필요하다: uv sync --group research"
            ) from exc
        return duckdb

    def _connect(self):
        return self._duckdb().connect(str(self.path))

    def _initialize(self) -> None:
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS external_content (
                    item_id VARCHAR PRIMARY KEY,
                    provider VARCHAR NOT NULL,
                    content_type VARCHAR NOT NULL,
                    symbol VARCHAR,
                    published_at TIMESTAMPTZ,
                    fetched_at TIMESTAMPTZ NOT NULL,
                    first_seen_at TIMESTAMPTZ NOT NULL,
                    url VARCHAR,
                    canonical_url VARCHAR,
                    title VARCHAR,
                    content VARCHAR NOT NULL,
                    author VARCHAR,
                    source VARCHAR,
                    content_hash VARCHAR NOT NULL,
                    url_hash VARCHAR NOT NULL,
                    language VARCHAR,
                    relevance DOUBLE,
                    sentiment DOUBLE,
                    metadata JSON NOT NULL,
                    UNIQUE(url_hash, content_hash)
                )
            """)
            # request_cache는 요청 응답만 보관하며 기사 원문과 수명·목적을 섞지 않는다.
            con.execute("""
                CREATE TABLE IF NOT EXISTS request_cache (
                    request_hash VARCHAR PRIMARY KEY,
                    payload VARCHAR NOT NULL,
                    cached_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL
                )
            """)

    def store(self, items: Sequence[ExternalContent]) -> tuple[str, ...]:
        """기사·게시물을 한 건씩 보관한다. 같은 URL·본문은 한 행으로 합쳐진다."""
        rows = [item.row() for item in items]
        if not rows:
            return ()
        with self._connect() as con:
            con.executemany("""
                INSERT OR IGNORE INTO external_content VALUES (
                    $item_id, $provider, $content_type, $symbol, $published_at,
                    $fetched_at, $first_seen_at, $url, $canonical_url, $title,
                    $content, $author, $source, $content_hash, $url_hash,
                    $language, $relevance, $sentiment, $metadata
                )
            """, rows)
        return tuple(str(row["item_id"]) for row in rows)

    def remember_request(
        self,
        identity: str,
        payload: str,
        *,
        cached_at: str,
        ttl_hours: int = 24,
    ) -> None:
        """같은 요청을 다시 던졌을 때 재사용할 응답 원문을 TTL 동안 보관한다."""
        if not str(identity).strip():
            raise ValueError("request identity is required")
        if not 1 <= int(ttl_hours) <= 168:
            raise ValueError("ttl_hours must be between 1 and 168")
        moment = parse_datetime(cached_at)
        with self._connect() as con:
            con.execute("DELETE FROM request_cache WHERE request_hash = ?", [identity])
            con.execute(
                "INSERT INTO request_cache VALUES (?, ?, ?, ?)",
                [identity, str(payload), moment, moment + timedelta(hours=int(ttl_hours))],
            )

    def get_request(self, identity: str, *, now: datetime | None = None) -> str | None:
        point = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._connect() as con:
            row = con.execute(
                "SELECT payload FROM request_cache WHERE request_hash = ? AND expires_at > ?",
                [identity, point],
            ).fetchone()
        return None if row is None else str(row[0])

    def iter_contents(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """사건 추출이 읽을 기사 행을 돌려준다. 기간·종목으로 좁히지 않으면 전부다."""
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("fetched_at >= ?")
            params.append(parse_datetime(since))
        if until is not None:
            clauses.append("fetched_at <= ?")
            params.append(parse_datetime(until))
        if symbols is not None:
            wanted = sorted({str(value).upper().strip() for value in symbols if str(value).strip()})
            if not wanted:
                return ()
            clauses.append(f"symbol IN ({', '.join('?' for _ in wanted)})")
            params.extend(wanted)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as con:
            result = con.execute(
                f"SELECT * FROM external_content{where} ORDER BY fetched_at, item_id", params
            )
            rows = result.fetchall()
            columns = [item[0] for item in result.description]
        contents: list[dict[str, Any]] = []
        for row in rows:
            value = dict(zip(columns, row, strict=True))
            if isinstance(value.get("metadata"), str):
                value["metadata"] = json.loads(value["metadata"])
            for key in ("published_at", "fetched_at", "first_seen_at"):
                if isinstance(value.get(key), datetime):
                    value[key] = value[key].astimezone(timezone.utc).isoformat()
            contents.append(value)
        return tuple(contents)

    def cleanup(self, *, now: datetime | None = None) -> dict[str, int]:
        point = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        cutoff = point - timedelta(days=self.retention_days)
        with self._connect() as con:
            expired_requests = con.execute(
                "SELECT count(*) FROM request_cache WHERE expires_at <= ?", [point]
            ).fetchone()[0]
            con.execute("DELETE FROM request_cache WHERE expires_at <= ?", [point])
            expired_content = con.execute(
                "SELECT count(*) FROM external_content WHERE fetched_at < ?", [cutoff]
            ).fetchone()[0]
            con.execute("DELETE FROM external_content WHERE fetched_at < ?", [cutoff])
        return {"requests_removed": int(expired_requests), "content_removed": int(expired_content)}

    def count(self) -> int:
        with self._connect() as con:
            return int(con.execute("SELECT count(*) FROM external_content").fetchone()[0])


__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "ExternalContent",
    "LocalEvidenceCache",
    "LocalEvidenceCacheError",
    "canonicalize_url",
    "request_hash",
]
