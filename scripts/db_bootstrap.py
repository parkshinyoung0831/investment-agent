"""빈 Supabase에 application schema를 처음부터 세운다.

`db/postgres/v1/*.sql`이 스키마의 단일 기준이다. 이 스크립트는 그 선언들을 FK 의존
순서대로 적용해 **선언만으로 clean environment를 재현할 수 있다는 것**을 실행 가능한
형태로 보장한다.

    python scripts/db_bootstrap.py plan
    python scripts/db_bootstrap.py apply --confirm <project-ref>
    python scripts/db_bootstrap.py apply --confirm <project-ref> --drop-first

``--drop-first``는 10개 application schema를 CASCADE로 지우고 다시 만든다. **데이터가
전부 사라진다.** Supabase 자체 영역(auth/storage/realtime/extensions/vault와 migration
metadata)은 건드리지 않는다.

드롭과 재생성은 한 트랜잭션에서 돈다. 중간에 실패해 스키마가 사라진 채로 남으면
PostgREST가 노출 목록에서 없는 스키마를 만나 Data API 전체가 503으로 죽는다.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import psycopg2

from scripts.postgres_schema_layout import (
    POSTGRES_V1_DIR,
    application_schemas,
    installation_files,
)

# SQL의 역할별 순서는 postgres_schema_layout이 단독 소유한다. 구조와 view는 같은
# 트랜잭션으로 설치한다.
INSTALLATION_SQL_FILES = tuple(path.name for path in installation_files())
SCHEMAS = application_schemas()


def _project_ref(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    user = parsed.username or ""
    if user.startswith("postgres.") and len(user) > len("postgres."):
        return user.split(".", 1)[1]
    host = parsed.hostname or ""
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return host[len("db.") : -len(".supabase.co")]
    return ""


def _connect():
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL이 필요하다 (.env). 로컬 전용이며 CI에 주입하지 않는다.")
    return psycopg2.connect(url), _project_ref(url)


def cmd_plan(_args) -> int:
    print("적용 순서 (구조 → view):\n")
    total = 0
    for path in installation_files():
        lines = path.read_text(encoding="utf-8").count("\n")
        total += lines
        print(f"  {path.relative_to(ROOT)}  ({lines} lines)")
    print(f"\n구조 SQL 합계 {total} lines · schema {len(SCHEMAS)}개")
    return 0


def _exposed_schemas(cur) -> list[str]:
    cur.execute(
        "SELECT setting FROM pg_roles r, unnest(r.rolconfig) AS setting"
        " WHERE r.rolname = 'authenticator' AND setting LIKE 'pgrst.db_schemas=%'"
    )
    row = cur.fetchone()
    if not row:
        return []
    return [part.strip() for part in row[0].split("=", 1)[1].split(",")]


def cmd_apply(args) -> int:
    conn, ref = _connect()
    if ref and args.confirm != ref:
        conn.close()
        raise SystemExit(f"--confirm {ref} 가 필요하다 (이 연결의 project ref).")
    conn.autocommit = False
    started = time.time()
    try:
        with conn.cursor() as cur:
            if args.drop_first:
                for schema in reversed(SCHEMAS):
                    cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                print(f"dropped {len(SCHEMAS)} schemas")

            for path in installation_files():
                cur.execute(path.read_text(encoding="utf-8"))
                print(f"  applied {path.relative_to(ROOT)}")

            exposed = _exposed_schemas(cur)
            missing = [s for s in SCHEMAS if s not in exposed]
            unknown = [
                s
                for s in exposed
                if s not in SCHEMAS and s not in ("public", "graphql_public")
            ]
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()

    print(f"\nCOMMIT · {time.time() - started:.1f}s")
    # 노출 목록에 실재하지 않는 스키마가 남으면 스키마 캐시를 만들지 못해 Data API가
    # 통째로 503이 된다. 드롭·생성 직후가 그 사고가 나기 가장 쉬운 지점이다.
    if missing:
        print(f"경고: PostgREST 노출 목록에 빠진 스키마: {', '.join(missing)}")
    if unknown:
        print(f"경고: 노출 목록에 실재하지 않는 스키마: {', '.join(unknown)} — Data API가 죽는다")
    if not missing and not unknown:
        print(f"PostgREST 노출 목록 정상 ({len(exposed)}개)")
    return 1 if (missing or unknown) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="적용 순서를 읽기만 한다")
    p_plan.set_defaults(func=cmd_plan)

    p_apply = sub.add_parser("apply", help="선언 SQL을 의존 순서대로 적용한다")
    p_apply.add_argument("--confirm", required=True, help="대상 project ref")
    p_apply.add_argument(
        "--drop-first",
        action="store_true",
        help="application schema 10개를 CASCADE로 지우고 다시 만든다 (데이터 전부 삭제)",
    )
    p_apply.set_defaults(func=cmd_apply)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
