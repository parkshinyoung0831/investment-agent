"""Supabase 용량을 실측하고, 회수 가능한 공간을 되찾는다.

Supabase Free는 **database size 500MB를 넘기면 프로젝트가 read-only로 전환**된다
(disk 1GB와는 별개이고 Free에는 autoscaling이 없다). 그래서 한도는 "언젠가 늘려야 할
숫자"가 아니라 넘기는 순간 모든 적재가 멈추는 벽이다. 이 도구가 그 벽까지의 거리를
재고, 벽에 가까워졌을 때 쓸 수 있는 유일한 수단을 제공한다.

    python scripts/db_capacity.py report
    python scripts/db_capacity.py report --json
    python scripts/db_capacity.py reclaim --confirm <project-ref>
    python scripts/db_capacity.py reclaim --confirm <project-ref> --tables fundamentals.segment_metrics

``report``는 읽기만 한다. ``reclaim``은 ``VACUUM (FULL, ANALYZE)``로 테이블을 다시 써서
빈 공간을 OS에 반환한다.

autovacuum이 dead tuple을 지워도 그 공간은 테이블 안에 남을 뿐 파일이 줄지 않는다.
Postgres 입장에서는 재사용 가능한 여유지만 ``pg_database_size``에는 그대로 계상되므로
Supabase 한도에는 **회수해야만 하는 낭비**다. DELETE나 retention 정리가 곧바로 용량
감소를 뜻하지 않는 이유도 같다.

``VACUUM FULL``은 ACCESS EXCLUSIVE 잠금을 잡고 테이블을 통째로 다시 쓴다. 쓰는 동안
그 테이블은 읽기도 막히고, 원본 크기만큼의 여유 디스크가 추가로 필요하다. 그래서
**스케줄 워크플로와 하네스를 세운 정비 창에서만** 돌린다.
"""
from __future__ import annotations

import argparse
import json
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

# Supabase Free: database size 500MB 초과 시 read-only.
FREE_PLAN_LIMIT_BYTES = 500 * 1000 * 1000
WARNING_RATIO = 0.70
CRITICAL_RATIO = 0.85

APP_SCHEMAS = (
    "universe",
    "market",
    "fundamentals",
    "macro",
    "institutional",
    "trading",
    "execution",
    "notifications",
    "operations",
    "reporting",
)

TABLE_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
PROJECT_REF_RE = re.compile(r"(?<![a-z0-9])([a-z]{20})(?![a-z0-9])")

# 재작성 비용이 회수량에 못 미치는 표는 건드리지 않는다.
RECLAIM_MIN_WASTE_BYTES = 4 * 1024 * 1024


def connect():
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL이 필요하다 (.env). Postgres 직결 전용이며 CI에는 주입하지 않는다.")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    return conn


def project_ref(conn) -> str:
    url = os.getenv("SUPABASE_DB_URL", "")
    found = PROJECT_REF_RE.findall(url)
    return found[0] if found else ""


def database_size(cur) -> int:
    cur.execute("SELECT pg_database_size(current_database())")
    return int(cur.fetchone()[0])


def table_stats(cur) -> list[dict]:
    """표별 실측 크기와 '이상적인 heap 크기'를 함께 낸다.

    이상치는 살아 있는 튜플의 실제 평균 폭에서 계산한다. 실측 heap이 이상치보다 크게
    벌어진 만큼이 재작성으로 회수 가능한 낭비다. 평균 폭은 표 전체를 훑어야 나오므로
    큰 표에서는 비싸다 — 그래서 heap이 임계치를 넘는 표만 잰다.
    """
    cur.execute(
        """
        SELECT n.nspname, c.relname,
               pg_total_relation_size(c.oid),
               pg_relation_size(c.oid),
               pg_indexes_size(c.oid),
               s.n_live_tup, s.n_dead_tup
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
         WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'm')
         ORDER BY pg_total_relation_size(c.oid) DESC
        """,
        (list(APP_SCHEMAS),),
    )
    rows = []
    for schema, name, total, heap, idx, live, dead in cur.fetchall():
        rows.append(
            {
                "table": f"{schema}.{name}",
                "total_bytes": int(total),
                "heap_bytes": int(heap),
                "index_bytes": int(idx),
                "live_tuples": int(live or 0),
                "dead_tuples": int(dead or 0),
                "ideal_heap_bytes": None,
                "waste_bytes": 0,
            }
        )

    for row in rows:
        if row["heap_bytes"] < RECLAIM_MIN_WASTE_BYTES:
            continue
        cur.execute(
            f'SELECT count(*), coalesce(avg(pg_column_size(t.*)), 0) FROM {row["table"]} t'  # noqa: S608 - 식별자는 pg_class에서 왔다
        )
        count, avg_width = cur.fetchone()
        # 24바이트 튜플 헤더 + 4바이트 line pointer.
        ideal = int(count * (float(avg_width) + 28))
        row["ideal_heap_bytes"] = ideal
        row["waste_bytes"] = max(0, row["heap_bytes"] - ideal)
    return rows


def unused_indexes(cur) -> list[dict]:
    cur.execute(
        """
        SELECT s.schemaname || '.' || s.relname, s.indexrelname, s.idx_scan,
               pg_relation_size(s.indexrelid), i.indisprimary, i.indisunique
          FROM pg_stat_user_indexes s
          JOIN pg_index i ON i.indexrelid = s.indexrelid
         WHERE s.schemaname = ANY(%s)
           AND pg_relation_size(s.indexrelid) > 1000000
         ORDER BY s.idx_scan ASC, pg_relation_size(s.indexrelid) DESC
        """,
        (list(APP_SCHEMAS),),
    )
    return [
        {
            "table": t,
            "index": idx,
            "scans": int(scans),
            "bytes": int(size),
            "is_primary": bool(pk),
            "is_unique": bool(uq),
        }
        for t, idx, scans, size, pk, uq in cur.fetchall()
    ]


def status_for(used: int) -> str:
    ratio = used / FREE_PLAN_LIMIT_BYTES
    if ratio >= CRITICAL_RATIO:
        return "critical"
    if ratio >= WARNING_RATIO:
        return "warning"
    return "ok"


def mb(value: int | float) -> str:
    return f"{value / 1_000_000:.1f}MB"


def cmd_report(args) -> int:
    conn = connect()
    cur = conn.cursor()
    try:
        used = database_size(cur)
        tables = table_stats(cur)
        indexes = unused_indexes(cur)
    finally:
        conn.close()

    reclaimable = sum(t["waste_bytes"] for t in tables)
    payload = {
        "database_bytes": used,
        "limit_bytes": FREE_PLAN_LIMIT_BYTES,
        "used_ratio": round(used / FREE_PLAN_LIMIT_BYTES, 4),
        "status": status_for(used),
        "headroom_bytes": FREE_PLAN_LIMIT_BYTES - used,
        "reclaimable_bytes": reclaimable,
        "tables": tables,
        "large_indexes": indexes,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] != "critical" else 1

    print(
        f"database {mb(used)} / {mb(FREE_PLAN_LIMIT_BYTES)} "
        f"({payload['used_ratio']:.1%}) -> {payload['status'].upper()}"
    )
    print(f"headroom {mb(payload['headroom_bytes'])} · 회수 가능 추정 {mb(reclaimable)}")
    # VACUUM FULL은 표를 통째로 다시 쓰므로 원본 크기만큼의 여유가 더 필요하다.
    # 가장 큰 표보다 여유가 적으면, 정작 공간이 급할 때 쓸 수 있는 유일한 수단이
    # 막힌다 — 한도까지 얼마 남았는지와는 다른 질문이라 따로 말한다.
    if tables and payload["headroom_bytes"] < tables[0]["total_bytes"]:
        print(
            f"주의: 여유({mb(payload['headroom_bytes'])})가 최대 표"
            f" {tables[0]['table']}({mb(tables[0]['total_bytes'])})보다 작다 —"
            " 지금은 그 표를 reclaim할 수 없다"
        )
    print()
    print(f"{'table':52s} {'total':>9s} {'heap':>9s} {'index':>9s} {'waste':>9s}")
    for t in tables[:20]:
        print(
            f"{t['table']:52s} {mb(t['total_bytes']):>9s} {mb(t['heap_bytes']):>9s} "
            f"{mb(t['index_bytes']):>9s} {mb(t['waste_bytes']):>9s}"
        )
    print()
    print("행당 비용 — 보존 기간을 정할 때 쓰는 단위 (총 bytes / live tuple)")
    print(f"{'table':52s} {'rows':>10s} {'bytes/row':>10s}")
    for t in tables[:8]:
        if t["live_tuples"] <= 0:
            continue
        print(
            f"{t['table']:52s} {t['live_tuples']:>10,d} "
            f"{t['total_bytes'] / t['live_tuples']:>10.0f}"
        )
    print(
        "  보존 기간을 바꿀 때는 (남길 행 수 × bytes/row)로 계산한다. 인덱스가 포함된"
        " 값이라 행을 지우면 인덱스도 같이 준다."
    )

    cold = [i for i in indexes if i["scans"] == 0 and not i["is_primary"]]
    if cold:
        print("\n한 번도 쓰이지 않은 큰 인덱스 (통계 리셋 시점 이후):")
        for i in cold:
            print(f"  {i['table']}.{i['index']:44s} {mb(i['bytes']):>9s}")
    return 0 if payload["status"] != "critical" else 1


def cmd_reclaim(args) -> int:
    conn = connect()
    cur = conn.cursor()
    ref = project_ref(conn)
    if ref and args.confirm != ref:
        conn.close()
        raise SystemExit(f"--confirm 값이 프로젝트와 다르다. 이 연결의 project ref는 {ref!r}이다.")

    try:
        before_db = database_size(cur)
        if args.tables:
            targets = []
            for name in args.tables:
                if not TABLE_RE.match(name):
                    raise SystemExit(f"테이블 이름이 schema.table 형태가 아니다: {name!r}")
                schema = name.split(".", 1)[0]
                if schema not in APP_SCHEMAS:
                    raise SystemExit(f"application schema가 아니다: {name!r}")
                targets.append(name)
        else:
            targets = [
                t["table"]
                for t in table_stats(cur)
                if t["waste_bytes"] >= RECLAIM_MIN_WASTE_BYTES
            ]

        if not targets:
            print("회수할 만한 낭비가 없다.")
            return 0

        print(f"database {mb(before_db)} · 대상 {len(targets)}개")
        results = []
        for name in targets:
            cur.execute("SELECT pg_total_relation_size(%s)", (name,))
            before = int(cur.fetchone()[0])
            started = time.time()
            cur.execute(f"VACUUM (FULL, ANALYZE) {name}")  # noqa: S608 - 위에서 형식·스키마 검증됨
            cur.execute("SELECT pg_total_relation_size(%s)", (name,))
            after = int(cur.fetchone()[0])
            results.append({"table": name, "before": before, "after": after})
            print(
                f"  {name:52s} {mb(before):>9s} -> {mb(after):>9s} "
                f"({mb(after - before):>9s}, {time.time() - started:.1f}s)"
            )
        after_db = database_size(cur)
        print(f"database {mb(before_db)} -> {mb(after_db)} ({mb(after_db - before_db)})")
        print(f"상태: {status_for(after_db).upper()} · headroom {mb(FREE_PLAN_LIMIT_BYTES - after_db)}")
    finally:
        conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_report = sub.add_parser("report", help="용량과 회수 가능량을 읽기만 한다")
    p_report.add_argument("--json", action="store_true")
    p_report.set_defaults(func=cmd_report)

    p_reclaim = sub.add_parser("reclaim", help="VACUUM FULL로 빈 공간을 OS에 반환한다")
    p_reclaim.add_argument("--confirm", required=True, help="대상 project ref")
    p_reclaim.add_argument("--tables", nargs="*", help="생략하면 낭비가 큰 표를 자동 선정")
    p_reclaim.set_defaults(func=cmd_reclaim)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
