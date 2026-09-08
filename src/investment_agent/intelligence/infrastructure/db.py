"""Intelligence의 DuckDB catalog와 Parquet archive 위치.

표 이름을 문자열 리터럴로 흩뿌리면 이름을 바꿀 때 한 곳을 빠뜨리고, 그 빠뜨림은
쿼리가 조용히 0행을 내는 방식으로 드러난다.
"""
from __future__ import annotations

from pathlib import Path

from investment_agent.platform.storage_paths import (
    INTELLIGENCE_DATABASE_PATH_ENV,
    INTELLIGENCE_PARQUET_ROOT_ENV,
    intelligence_database_path,
    intelligence_parquet_root,
)

DATABASE_PATH_ENV = INTELLIGENCE_DATABASE_PATH_ENV
DEFAULT_DATABASE_PATH = Path("data/local/intelligence/intelligence.duckdb")
DEFAULT_PARQUET_ROOT = Path("data/local/intelligence/parquet")
DDL_DIR = Path("db/duckdb/intelligence/v1")

# 본문은 Parquet view로만 읽는다. 아래 두 table은 고유성·retention·mention 연결에
# 필요한 작은 index이며 title/body/summary를 중복 저장하지 않는다.
# 뉴스와 소셜이 한 표를 쓴다 — `content_kind`가 가른다.
T_CONTENT = "content_index"
T_MENTIONS = "entity_mentions"

V_NEWS = "news_articles"
V_SOCIAL = "social_posts"

V_FRESHNESS = "intelligence_freshness"
V_MENTION_DAILY = "ticker_mention_daily"


def default_database_path() -> Path:
    """이번 실행이 쓸 Intelligence DB 경로."""
    return intelligence_database_path()


def parquet_root(database_path: Path | str | None = None) -> Path:
    """본문 Parquet 루트.

    기본 production 경로는 명시적으로 고정한다. 테스트나 별도 profile에서 DuckDB
    경로를 주면 그 파일 옆에 둬서 서로의 90일 archive를 공유하지 않게 한다.
    """
    return intelligence_parquet_root(database_path)


__all__ = [
    "DATABASE_PATH_ENV",
    "DEFAULT_PARQUET_ROOT",
    "DDL_DIR",
    "DEFAULT_DATABASE_PATH",
    "T_MENTIONS",
    "T_CONTENT",
    "V_NEWS",
    "V_SOCIAL",
    "V_FRESHNESS",
    "V_MENTION_DAILY",
    "default_database_path",
    "parquet_root",
]
