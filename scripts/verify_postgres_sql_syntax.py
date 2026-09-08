"""`db/postgres/v1/*.sql`이 유효한 PostgreSQL 구문인지 오프라인으로 검증한다.

`v1_schema_probe.py`는 실제 DB에 임시 스키마로 심어 적용 가능성까지 확인하지만
네트워크·자격증명이 필요하다. 이 스크립트는 `pglast`로 파싱만 하므로 DB 없이도
CI·로컬 어디서나 돈다 — 괄호가 안 맞거나 예약어를 잘못 쓴 실수를 즉시 잡는다.

    python scripts/verify_postgres_sql_syntax.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from pglast import parser

ROOT = Path(__file__).resolve().parents[1]
POSTGRES_V1_DIR = ROOT / "db" / "postgres" / "v1"


def sql_files() -> list[Path]:
    return sorted(POSTGRES_V1_DIR.glob("*.sql"))


def check_file(path: Path) -> str | None:
    """구문 오류가 있으면 사람이 읽을 오류 메시지를, 없으면 None을 돌려준다."""
    try:
        parser.parse_sql(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pglast raises its own ParseError subclasses
        return f"{path.relative_to(ROOT)}: {exc}"
    return None


def check_all() -> list[str]:
    errors = []
    for path in sql_files():
        error = check_file(path)
        if error:
            errors.append(error)
    return errors


def main() -> int:
    files = sql_files()
    if not files:
        print(f"no .sql files found under {POSTGRES_V1_DIR}")
        return 1
    errors = check_all()
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"{len(files)}개 파일 구문 확인 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
