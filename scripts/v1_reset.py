"""투자 앱 소유 객체만 지우고 빈 v1 스키마를 적용한다.

이 도구는 앱 데이터를 복사하지 않는다. ``--confirm-reset``은 의도적으로
필수다. Supabase 관리 스키마(auth/storage/realtime 등)와 public/graphql 객체는 대상이
아니다. PostgREST 노출 목록은 전체 v1 선언이 성공한 뒤 한 번에 교체한다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.postgres_schema_layout import application_schemas, installation_files

# 현재 이 투자 앱이 소유하는 객체만. Supabase 시스템/다른 프로젝트의 스키마를 넓게
# 지우는 CASCADE는 절대 하지 않는다.
V1_SCHEMAS = application_schemas()
# Supabase 관리 스키마(auth/storage/realtime 등)는 이 목록에 절대 넣지 않는다.
# trading·execution·operations 판단/실행/운영 상태는 실행 컴퓨터의
# data/local/runtime/runtime.sqlite3가 소유한다(platform/runtime_store.py) — 여기서 지우고
# 다시 만들 Supabase 객체가 아니다.
APP_SCHEMAS = V1_SCHEMAS
POSTGREST_SCHEMAS = ("public", "graphql_public", *V1_SCHEMAS)
STRUCTURE_SQL_FILES = tuple(path.name for path in installation_files())


def sql_files() -> list[Path]:
    return installation_files()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-reset", action="store_true", help="앱 데이터 삭제를 명시적으로 승인")
    args = parser.parse_args(argv)
    if not args.confirm_reset:
        parser.error("--confirm-reset 없이는 DB를 변경하지 않습니다")

    load_dotenv(ROOT / ".env")
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL 이 필요합니다 (.env 로컬 전용).")

    conn = psycopg2.connect(url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for schema in APP_SCHEMAS:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            for path in sql_files():
                cur.execute(path.read_text(encoding="utf-8"))
            exposed = ", ".join(POSTGREST_SCHEMAS)
            cur.execute("ALTER ROLE authenticator SET pgrst.db_schemas = %s", (exposed,))
            cur.execute("NOTIFY pgrst, 'reload schema'")
            cur.execute("NOTIFY pgrst, 'reload config'")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print("v1 reset complete")
    print("dropped=" + ",".join(APP_SCHEMAS))
    print("applied=" + ",".join(path.name for path in sql_files()))
    print("postgrest=" + ",".join(POSTGREST_SCHEMAS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
