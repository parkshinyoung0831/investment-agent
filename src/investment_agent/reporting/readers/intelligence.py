"""화면이 쓰는 Intelligence 읽기 계약.

## 읽기 전용 외의 경로를 두지 않는다

DuckDB는 파일당 쓰기 프로세스가 하나다. Streamlit이 쓰기 모드로 열면 수집 잡이
그 파일을 못 열어 죽는다. 그래서 이 모듈은 `read_only=True`로만 저장소를 연다.

## 저장소가 없어도 화면은 살아 있어야 한다

수집이 한 번도 돌지 않은 노트북에서 파일이 없는 것은 오류가 아니라 상태다.
예외 대신 `available=False`를 돌려준다.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from investment_agent.intelligence.infrastructure.db import default_database_path
from investment_agent.intelligence.repository import IntelligenceRepository
from investment_agent.intelligence.infrastructure.sources.news.provider import sanitize_message
from investment_agent.platform.cache import cache_data
from investment_agent.platform.clock import utc_now
from investment_agent.platform.db.duckdb import DuckDBStoreError
from investment_agent.platform.logging import get_logger, log_fields

log = get_logger(__name__)

# 외부에서 온 텍스트. 저장은 원문이지만 화면으로 나갈 때는 가린다.
_UNTRUSTED_FIELDS = ("title", "summary", "body", "flair", "source_name")


def _repository_path() -> Path:
    return default_database_path()


def _reader() -> IntelligenceRepository:
    return IntelligenceRepository(_repository_path(), read_only=True)


def _sanitised(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """외부 본문을 화면 계약으로 넘기기 전에 URL·자격증명 모양을 가린다."""
    cleaned = []
    for row in rows:
        item = dict(row)
        for field in _UNTRUSTED_FIELDS:
            if item.get(field):
                item[field] = sanitize_message(item[field])
        cleaned.append(item)
    return cleaned


@cache_data(ttl="5m", max_entries=8)
def load_overview() -> dict[str, Any]:
    """freshness와 최근 실행 기록. 정리가 실제로 돌았는지도 여기서 보인다."""
    try:
        reader = _reader()
        # message는 자유 텍스트라 provider 오류 문구가 들어올 수 있다
        runs = [
            {**run, "message": sanitize_message(run["message"]) if run.get("message") else None}
            for run in reader.recent_runs(limit=10)
        ]
        return {
            "available": True,
            "path": _repository_path().as_posix(),
            "freshness": reader.freshness(),
            "runs": runs,
        }
    except DuckDBStoreError as error:
        log.info(
            "intelligence store unavailable for overview",
            extra=log_fields(error_type=type(error).__name__),
        )
        return {
            "available": False,
            "path": _repository_path().as_posix(),
            "freshness": [],
            "runs": [],
        }


@cache_data(ttl="5m", max_entries=8)
def load_news(limit: int = 50) -> list[dict[str, Any]]:
    try:
        return _sanitised(_reader().recent_news(limit=limit))
    except DuckDBStoreError as error:
        log.info(
            "intelligence store unavailable for news",
            extra=log_fields(error_type=type(error).__name__),
        )
        return []


@cache_data(ttl="5m", max_entries=8)
def load_social(limit: int = 50) -> list[dict[str, Any]]:
    try:
        return _sanitised(_reader().recent_social(limit=limit))
    except DuckDBStoreError as error:
        log.info(
            "intelligence store unavailable for social",
            extra=log_fields(error_type=type(error).__name__),
        )
        return []


@cache_data(ttl="5m", max_entries=8)
def load_trending(days: int = 7, limit: int = 20) -> list[dict[str, Any]]:
    """최근 며칠의 언급량 상위 종목. 기간을 좁혀 90일 전체 스캔을 피한다."""
    since = (utc_now() - timedelta(days=int(days))).date().isoformat()
    try:
        return _reader().mention_counts(since=since, limit=limit)
    except DuckDBStoreError as error:
        log.info(
            "intelligence store unavailable for trending",
            extra=log_fields(error_type=type(error).__name__),
        )
        return []


__all__ = ["load_news", "load_overview", "load_social", "load_trending"]
