"""macro 발표 표의 오염 행을 정리한다 — 기본은 dry-run(읽기만).

지우는 것은 두 가지이고, 둘 다 고친 코드가 다시 만들 수 있는 파생 행이다.

1. 단위가 어긋난 자체 예상(`own_model`): 변환 measure(MOM·변화량·YOY)의 예상이 원값 수준으로
   저장된 행. `econ_baseline_*` 출처이고 measure 변환이 `level`이 아닌 것.
   백필 출처(`alfred_baseline_*`)는 정상 단위라 건드리지 않는다.
2. 유령 발표 이벤트: 주간 지표의 관측 요일(`series_config.json`의 `observation_weekday`)과
   다른 요일의 `ref_period`를 가지면서 관측이 없는 이벤트. 그 요일이 아닌 날에는 관측이 생길 수 없다.
   `release_events` 삭제는 일정 버전·예상 스냅샷이 FK CASCADE로 함께 지워진다.

실행:
    python scripts/cleanup_macro_release_artifacts.py                          # 대상만 센다
    python scripts/cleanup_macro_release_artifacts.py --apply --confirm <project ref>

`--apply`는 한 트랜잭션에서 지운다. 백업은 만들지 않는다 — 지운 행은 고친 코드가 다시 만든다.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from investment_agent.data.macro.domain.releases import release_catalog as catalog  # noqa: E402

STATEMENT_TIMEOUT_MS = 60_000


def project_ref() -> str:
    match = re.match(r"https://([a-z0-9]+)\.supabase\.co", os.environ.get("SUPABASE_URL", ""))
    if not match:
        raise SystemExit("SUPABASE_URL에서 project ref를 읽지 못했다 — 확인 없이는 지우지 않는다")
    return match.group(1)


def weekday_by_series() -> dict[str, int]:
    """series_id → PostgreSQL isodow(월=1 … 일=7). 카탈로그가 유일한 출처다."""
    out: dict[str, int] = {}
    for series_id in catalog.series_ids():
        schedule = catalog.series_config(series_id).get("source_contract", {}).get("schedule", {})
        if "observation_weekday" in schedule:
            out[series_id] = int(schedule["observation_weekday"]) + 1
    return out


OWN_MODEL_SQL = """
    SELECT f.series_key, f.ref_period, f.measure_id, f.forecast_kind, f.source_code,
           f.value, f.effective_at, f.collected_at
    FROM macro.forecast_snapshots f
    JOIN macro.measures m USING (measure_id)
    WHERE f.forecast_kind = 'own_model'
      AND f.source_code LIKE 'econ\\_baseline%%'
      AND m.transform <> 'level'
"""

GHOST_SQL = """
    SELECT e.series_key, s.series_code, e.ref_period
    FROM macro.release_events e
    JOIN macro.series s USING (series_key)
    WHERE s.series_code = %(series_id)s
      AND extract(isodow FROM e.ref_period)::int <> %(weekday)s
      AND NOT EXISTS (
          SELECT 1 FROM macro.economic_observations o
          WHERE o.series_key = e.series_key AND o.observation_date = e.ref_period)
"""


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔(cp949)에서 em dash가 출력을 끊지 않게
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="실제로 지운다(기본은 개수만 센다)")
    parser.add_argument("--confirm", help="대상 project ref — --apply에 필수")
    args = parser.parse_args()
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    ref = project_ref()
    if args.apply and args.confirm != ref:
        raise SystemExit(f"--confirm이 project ref({ref})와 다르다 — 지우지 않는다")

    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    conn.set_session(readonly=not args.apply, autocommit=False)
    with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
        cur.execute(OWN_MODEL_SQL)
        own_model = cur.fetchall()
        ghosts: list[dict] = []
        for series_id, weekday in sorted(weekday_by_series().items()):
            cur.execute(GHOST_SQL, {"series_id": series_id, "weekday": weekday})
            ghosts.extend(cur.fetchall())
        print(f"project {ref}")
        print(f"단위 오염 own_model 행: {len(own_model)}")
        by_series: dict[str, int] = {}
        for row in ghosts:
            by_series[row["series_code"]] = by_series.get(row["series_code"], 0) + 1
        print(f"유령 발표 이벤트: {len(ghosts)} {by_series}")
        if not args.apply:
            print("dry-run — 지우려면 --apply --confirm <project ref>")
            return 0

        for row in own_model:
            cur.execute(
                "DELETE FROM macro.forecast_snapshots WHERE series_key=%s AND ref_period=%s AND measure_id=%s "
                "AND forecast_kind=%s AND effective_at=%s AND collected_at=%s",
                (row["series_key"], row["ref_period"], row["measure_id"], row["forecast_kind"],
                 row["effective_at"], row["collected_at"]),
            )
        for row in ghosts:
            cur.execute(
                "DELETE FROM macro.release_events WHERE series_key=%s AND ref_period=%s",
                (row["series_key"], row["ref_period"]),
            )
        print(f"삭제 own_model {len(own_model)} · 이벤트 {len(ghosts)} (같은 트랜잭션에서 commit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
