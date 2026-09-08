"""PostgreSQL v1 선언 SQL의 역할별 설치 순서.

번호는 설치 역할을 나타낸다. ``00``은 공통 확장, ``10``~``50``은 금융 사실
스키마, ``90``은 모든 사실 스키마가 선 뒤에 만드는 read-only view다. 선언은
수집된 행에 의존하지 않으므로 빈 DB에 한 트랜잭션으로 전부 선다.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_V1_DIR = ROOT / "db" / "postgres" / "v1"

STRUCTURE_SQL_FILES = (
    "00_extensions.sql",
    "10_universe.sql",
    "20_market.sql",
    "30_fundamentals.sql",
    "40_macro.sql",
    "50_institutional.sql",
)
VIEW_SQL_FILES = ("90_reporting.sql",)

SCHEMA_OF_STRUCTURE_FILE = {
    "00_extensions.sql": None,
    "10_universe.sql": "universe",
    "20_market.sql": "market",
    "30_fundamentals.sql": "fundamentals",
    "40_macro.sql": "macro",
    "50_institutional.sql": "institutional",
}
SCHEMA_OF_INSTALLATION_FILE = {
    **SCHEMA_OF_STRUCTURE_FILE,
    "90_reporting.sql": "reporting",
}


def _paths(names: tuple[str, ...]) -> list[Path]:
    files = [POSTGRES_V1_DIR / name for name in names]
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        raise RuntimeError("db/postgres/v1 SQL 파일이 없습니다: " + ", ".join(missing))
    return files


def installation_files() -> list[Path]:
    """빈 DB 설치 순서: 확장·사실 스키마를 만든 뒤 reporting view를 만든다."""
    return _paths((*STRUCTURE_SQL_FILES, *VIEW_SQL_FILES))


def application_schemas() -> tuple[str, ...]:
    """v1이 소유하는 Supabase application schema의 FK 설치 순서."""
    return tuple(schema for schema in SCHEMA_OF_INSTALLATION_FILE.values() if schema)
