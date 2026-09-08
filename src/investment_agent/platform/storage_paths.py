"""로컬 저장소의 canonical 경로와 이전 기본 경로 계약."""
from __future__ import annotations

import os
from pathlib import Path

LOCAL_DATA_ROOT_ENV = "AI_INVESTOR_LOCAL_DATA_ROOT"
LOCAL_ARTIFACT_ROOT_ENV = "AI_INVESTOR_LOCAL_ARTIFACT_ROOT"
INTELLIGENCE_DATABASE_PATH_ENV = "AI_INVESTOR_INTELLIGENCE_DB_PATH"
INTELLIGENCE_PARQUET_ROOT_ENV = "AI_INVESTOR_INTELLIGENCE_PARQUET_ROOT"
RESEARCH_ROOT_ENV = "INVESTMENT_AGENT_RESEARCH_ROOT"
RUNTIME_DATABASE_PATH_ENV = "AI_INVESTOR_RUNTIME_DB_PATH"
EVIDENCE_CACHE_PATH_ENV = "AI_INVESTOR_NEWS_CACHE_PATH"
MARKET_CHANGE_MANIFEST_PATH_ENV = "AI_INVESTOR_MARKET_CHANGE_MANIFEST_PATH"

DEFAULT_LOCAL_DATA_ROOT = Path("data/local")
DEFAULT_LOCAL_ARTIFACT_ROOT_NAME = "artifacts"
DEFAULT_INTELLIGENCE_DATABASE_NAME = "intelligence.duckdb"
DEFAULT_RESEARCH_DATABASE_NAME = "research.duckdb"
DEFAULT_RUNTIME_DATABASE_NAME = "runtime.sqlite3"
DEFAULT_EVIDENCE_CACHE_NAME = "news_social.duckdb"
DEFAULT_MARKET_CHANGE_MANIFEST_NAME = "market_change_manifest.json"


def repository_root() -> Path:
    """선언 SQL(`db/`)이 있는 저장소 루트.

    `parents[N]`로 깊이를 세면 모듈을 한 단계 옮기는 순간 조용히 다른 폴더를
    가리킨다 — 실제로 그렇게 되어 "no such table"이 났다. 깊이 대신 표식을 찾는다.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "db").is_dir():
            return parent
    raise RuntimeError("저장소 루트를 찾지 못했다 (pyproject.toml + db/)")


def _configured_path(name: str) -> Path | None:
    configured = os.environ.get(name, "").strip()
    return Path(configured) if configured else None


def local_data_root() -> Path:
    return _configured_path(LOCAL_DATA_ROOT_ENV) or DEFAULT_LOCAL_DATA_ROOT


def local_artifact_root() -> Path:
    return (
        _configured_path(LOCAL_ARTIFACT_ROOT_ENV)
        or local_data_root() / DEFAULT_LOCAL_ARTIFACT_ROOT_NAME
    )


def intelligence_database_path() -> Path:
    return (
        _configured_path(INTELLIGENCE_DATABASE_PATH_ENV)
        or local_data_root() / "intelligence" / DEFAULT_INTELLIGENCE_DATABASE_NAME
    )


def intelligence_parquet_root(
    database_path: Path | str | None = None,
) -> Path:
    configured = _configured_path(INTELLIGENCE_PARQUET_ROOT_ENV)
    if configured is not None:
        return configured
    if database_path is None or Path(database_path) == intelligence_database_path():
        return local_data_root() / "intelligence" / "parquet"
    return Path(database_path).parent / "parquet" / "intelligence"


def research_root() -> Path:
    return _configured_path(RESEARCH_ROOT_ENV) or local_data_root() / "research"


def research_database_path() -> Path:
    return research_root() / DEFAULT_RESEARCH_DATABASE_NAME


def runtime_database_path() -> Path:
    return (
        _configured_path(RUNTIME_DATABASE_PATH_ENV)
        or local_data_root() / "runtime" / DEFAULT_RUNTIME_DATABASE_NAME
    )


def evidence_cache_path() -> Path:
    """LLM 판단 시점에 채워지는 뉴스·소셜 lazy cache.

    스케줄 능동 수집(`intelligence_database_path()`)과 다른 저장소다 — 채우는
    시점도 보존 정책도 다르다. 다만 **경로는 같은 뿌리를 따라야 한다**:
    전에는 여기만 상수로 박혀 있어서 `AI_INVESTOR_LOCAL_DATA_ROOT`로 로컬
    데이터를 옮겨도 이 파일만 옛 자리에 남았다.
    """
    return (
        _configured_path(EVIDENCE_CACHE_PATH_ENV)
        or local_data_root() / DEFAULT_EVIDENCE_CACHE_NAME
    )


def market_change_manifest_path() -> Path:
    return (
        _configured_path(MARKET_CHANGE_MANIFEST_PATH_ENV)
        or local_artifact_root() / DEFAULT_MARKET_CHANGE_MANIFEST_NAME
    )


def legacy_candidates(store: str) -> tuple[Path, ...]:
    candidates = {
        "intelligence": (Path("data/local/intelligence.duckdb"),),
        "research": (Path("artifacts/research/research.duckdb"),),
        "runtime": (Path("data/local/runtime.sqlite3"),),
    }
    try:
        return candidates[store]
    except KeyError as exc:
        raise ValueError(f"unknown local store: {store}") from exc


__all__ = [
    "DEFAULT_INTELLIGENCE_DATABASE_NAME",
    "DEFAULT_EVIDENCE_CACHE_NAME",
    "DEFAULT_LOCAL_DATA_ROOT",
    "DEFAULT_MARKET_CHANGE_MANIFEST_NAME",
    "DEFAULT_RESEARCH_DATABASE_NAME",
    "DEFAULT_RUNTIME_DATABASE_NAME",
    "EVIDENCE_CACHE_PATH_ENV",
    "INTELLIGENCE_DATABASE_PATH_ENV",
    "INTELLIGENCE_PARQUET_ROOT_ENV",
    "LOCAL_ARTIFACT_ROOT_ENV",
    "LOCAL_DATA_ROOT_ENV",
    "MARKET_CHANGE_MANIFEST_PATH_ENV",
    "RESEARCH_ROOT_ENV",
    "RUNTIME_DATABASE_PATH_ENV",
    "evidence_cache_path",
    "intelligence_database_path",
    "intelligence_parquet_root",
    "legacy_candidates",
    "local_artifact_root",
    "local_data_root",
    "market_change_manifest_path",
    "research_database_path",
    "research_root",
    "runtime_database_path",
]
