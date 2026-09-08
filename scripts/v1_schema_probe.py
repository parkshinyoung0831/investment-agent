"""`db/postgres/v1/*.sql`을 임시 스키마에 심어 실제로 서는지 확인하고 지운다.

v1 선언은 아직 어디에도 적용되지 않았다. 그렇다고 눈으로만 읽으면 컬럼을 지우고 그
인덱스를 남기는 류의 실수가 그대로 남는다 — 실제로 그런 실수가 있었고 이 도구가 잡았다.

    python scripts/v1_schema_probe.py                 # 전체
    python scripts/v1_schema_probe.py --only universe market

기존 스키마는 건드리지 않는다. 선언 안의 스키마 이름을 `v1probe_<name>`으로 바꿔 심고,
끝나면 성공·실패와 무관하게 지운다. 라이브 데이터와 이름이 겹치지 않으므로 운영 중에도
안전하다.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import psycopg2

from scripts.postgres_schema_layout import (
    SCHEMA_OF_INSTALLATION_FILE,
    installation_files,
)

PROBE_PREFIX = "v1probe_"
STRUCTURE_SQL_FILES = tuple(path.name for path in installation_files())
SCHEMA_OF_FILE = SCHEMA_OF_INSTALLATION_FILE


def declared_files() -> list[Path]:
    return installation_files()


# 전역(롤·클러스터) 상태를 바꾸는 구문. 임시 검사에서 실행되면 라이브에 흔적이 남는다.
_GLOBAL_STATE_RE = re.compile(
    r"(?ims)^\s*DO\s*\$\$(?:(?!\$\$).)*?pgrst\.db_schemas(?:(?!\$\$).)*?\$\$\s*;"
    r"|^\s*ALTER\s+ROLE\s+authenticator\b[^;]*;"
    r"|^\s*NOTIFY\s+pgrst\b[^;]*;"
)


def strip_global_state(text: str) -> str:
    """PostgREST 노출 목록 같은 전역 설정을 만지는 구문을 뺀다.

    검사는 "이 선언이 서는가"를 묻는 것이지 "노출 목록을 바꿔도 되는가"가 아니다.
    빼지 않으면 임시 스키마 이름이 라이브 설정에 들어가고, 검사가 끝나 그 스키마를
    지우는 순간 PostgREST가 없는 스키마를 만나 Data API 전체가 멈춘다.
    """
    return _GLOBAL_STATE_RE.sub("", text)


def probe_sql(text: str, schemas: list[str]) -> str:
    """선언 안의 스키마 이름을 임시 이름으로 바꾼다.

    확장(`extensions`)과 Supabase 롤은 그대로 둔다 — 임시로 복제할 수 없고, 복제하면
    권한 선언이 실제와 달라져 검증 의미가 없다.
    """
    out = strip_global_state(text)
    for name in schemas:
        out = re.sub(rf"\b{name}\b", f"{PROBE_PREFIX}{name}", out)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="이 스키마만 검증한다.")
    parser.add_argument("--keep", action="store_true", help="검사 후 임시 스키마를 남긴다.")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL 이 필요합니다 (.env 로컬 전용).")

    files = declared_files()
    if not files:
        raise SystemExit(f"{POSTGRES_V1_DIR} 에 선언 SQL이 없습니다.")

    known = {f.name: SCHEMA_OF_FILE.get(f.name) for f in files}
    unknown = [name for name, schema in known.items() if name not in SCHEMA_OF_FILE]
    if unknown:
        raise SystemExit(f"SCHEMA_OF_FILE에 없는 파일: {unknown}")

    schemas = [s for s in known.values() if s]
    if args.only:
        wanted = set(args.only)
        files = [f for f in files if known[f.name] is None or known[f.name] in wanted]

    conn = psycopg2.connect(url)
    conn.autocommit = True
    created: list[str] = []
    failed = False
    try:
        with conn.cursor() as cur:
            for schema in schemas:
                cur.execute(f"DROP SCHEMA IF EXISTS {PROBE_PREFIX}{schema} CASCADE")

        for path in files:
            text = probe_sql(path.read_text(encoding="utf-8"), schemas)
            try:
                with conn.cursor() as cur:
                    cur.execute(text)
            except Exception as exc:  # noqa: BLE001 - 어느 파일이 왜 못 서는지가 결과물이다
                print(f"  FAIL  {path.name}: {str(exc).splitlines()[0]}")
                failed = True
                break
            schema = known[path.name]
            if schema:
                created.append(schema)
                with conn.cursor() as cur:
                    cur.execute(
                        """select count(*) from information_schema.tables
                            where table_schema = %s and table_type = 'BASE TABLE'""",
                        (f"{PROBE_PREFIX}{schema}",),
                    )
                    tables = cur.fetchone()[0]
                    cur.execute(
                        """select count(*) from information_schema.views
                            where table_schema = %s""",
                        (f"{PROBE_PREFIX}{schema}",),
                    )
                    views = cur.fetchone()[0]
                print(f"  OK    {path.name:26} 표 {tables:>3} · 뷰 {views:>3}")
            else:
                print(f"  OK    {path.name}")
    finally:
        if not args.keep:
            with conn.cursor() as cur:
                for schema in schemas:
                    cur.execute(f"DROP SCHEMA IF EXISTS {PROBE_PREFIX}{schema} CASCADE")
        conn.close()

    if failed:
        return 1
    print(f"\n검증 통과 · 스키마 {len(created)}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
