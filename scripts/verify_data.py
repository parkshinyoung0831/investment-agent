"""적재된 데이터가 지켜야 할 불변식을 실제 DB에 물어본다.

`verify_integration.py`가 "코드가 부르는 조회가 아직 성립하는가"를 본다면, 이쪽은
"들어 있는 값이 말이 되는가"를 본다. 두 검사는 서로 다른 불변식을 확인한다.

여기 있는 검사는 대부분 DB 제약이 이미 막아 주는 것과 같은 조건이다. 그래도 다시
확인하는 이유는, 제약은 *선언*에만 있고 라이브 테이블에는 빠져 있을 수 있기 때문이다.
선언 적용 가능성은 `v1_schema_probe.py`가 확인하고, 이 스크립트는 실제 값의 상태를
확인한다.

    python scripts/verify_data.py
    python scripts/verify_data.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import psycopg2

# (검사 이름, SQL, 기대값). SQL은 스칼라 하나를 돌려줘야 한다.
CHECKS: tuple[tuple[str, str, int], ...] = (
    ("market.no_duplicate_bars",
     "select count(*) from (select security_id, trade_date from market.prices_daily"
     " group by 1, 2 having count(*) > 1) d", 0),
    ("market.prices_positive",
     "select count(*) from market.prices_daily"
     " where least(open, high, low, close) <= 0", 0),
    ("market.ohlc_bounds",
     "select count(*) from market.prices_daily"
     " where high < greatest(open, low, close) or low > least(open, high, close)", 0),
    ("market.ticker_exists",
     "select count(*) from market.prices_daily p"
     " left join universe.securities s using (security_id) where s.security_id is null", 0),

    ("universe.entities_named",
     "select count(*) from universe.entities"
     " where company_name is null or btrim(company_name) = ''", 0),
    ("universe.tracked_has_cik",
     "select count(*) from universe.securities where is_tracked and cik is null", 0),

    # 관심목록은 이 저장소가 유일하게 보존하기로 한 데이터다. 비어 있으면 등록이
    # 통째로 날아간 것이므로 다른 무엇보다 먼저 안다. 개수 자체는 사람이 정하는
    # 값이라 여기서 재지 않는다 — 종목 하나를 더한 날 검증이 빨개질 이유가 없다.
    ("universe.watchlist_has_members",
     "select count(*) from (select 1 from universe.entities where is_watchlisted limit 1) d", 1),
    # 보여줄 대표 종목이 없는 관심 기업은 카드에서 조용히 사라진다.
    ("universe.watchlist_has_a_tracked_security",
     "select count(*) from universe.entities e where e.is_watchlisted and not exists"
     " (select 1 from universe.securities s where s.cik = e.cik and s.is_tracked)", 0),
    # 보고 있는데 시작일을 모르면 "언제부터의 사건인가"를 답할 수 없다.
    ("universe.watchlist_has_watch_from",
     "select count(*) from universe.entities"
     " where is_watchlisted and watch_from is null", 0),

    ("fundamentals.one_row_per_fiscal_period_and_filing",
     "select count(*) from (select cik, period_end, source_accession_no"
     " from fundamentals.financials group by 1, 2, 3 having count(*) > 1) d", 0),
    ("fundamentals.segment_cik_exists",
     "select count(*) from fundamentals.segment_metrics m"
     " left join universe.entities e using (cik) where e.cik is null", 0),
    ("fundamentals.segment_coverage_positive",
     "select count(*) from fundamentals.segment_metrics"
     " where coverage_ratio is not null and coverage_ratio <= 0", 0),
    ("fundamentals.filing_form_known",
     "select count(*) from fundamentals.filings where form_type not in"
     " ('10-Q', '10-Q/A', '10-K', '10-K/A', '8-K')", 0),

    ("institutional.position_has_filing",
     "select count(*) from institutional.positions p"
     " left join institutional.filings f using (accession_no)"
     " where f.accession_no is null", 0),

    # 관측은 append-only 빈티지 원장이다 — 같은 (series, 관측일)에 여러 행이 있는
    # 것이 정상이고, 중복은 빈티지까지 같을 때만 중복이다.
    ("macro.no_duplicate_observations",
     "select count(*) from (select series_key, observation_date, vintage_at, available_at"
     " from macro.economic_observations group by 1, 2, 3, 4 having count(*) > 1) d", 0),
    ("macro.values_present",
     "select count(*) from macro.economic_observations where value is null", 0),
    # 지표는 domain이 정한 표에 쌓인다 — 시장 지표를 경제 발표 표에서 찾으면
    # 정상인 32개가 통째로 결손으로 잡힌다.
    #
    # 발표 일정이 하나도 없는 series는 수집 대상이 아니다(ISM처럼 라이선스 때문에
    # unsupported로 둔 것). 일정은 있는데 값이 없는 것만 진짜 공백이다.
    ("macro.scheduled_series_have_observations",
     "select count(*) from macro.series s where s.domain = 'economic_release'"
     " and exists (select 1 from macro.release_events e where e.series_key = s.series_key)"
     " and not exists"
     " (select 1 from macro.economic_observations o where o.series_key = s.series_key)", 0),
    ("macro.market_series_have_observations",
     "select count(*) from macro.series s where s.domain = 'market_indicator'"
     " and not exists"
     " (select 1 from macro.market_observations o where o.series_key = s.series_key)", 0),

    # 빈티지(자료가 유효해진 시각)가 수집 시각보다 뒤면 PIT 재구성이 미래를 본다.
    ("macro.observation_time_order",
     "select count(*) from macro.economic_observations"
     " where vintage_at > available_at + interval '5 minutes'", 0),
    ("macro.forecast_time_order",
     "select count(*) from macro.forecast_snapshots"
     " where effective_at > collected_at + interval '5 minutes'", 0),
    ("macro.one_release_per_period",
     "select count(*) from (select series_key, ref_period from macro.release_events"
     " group by 1, 2 having count(*) > 1) d", 0),

)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts/verify_data.py")
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력한다")
    args = parser.parse_args(argv)

    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL이 필요하다 (.env). 로컬 전용이며 CI에 주입하지 않는다.")

    conn = psycopg2.connect(url)
    results = []
    try:
        with conn.cursor() as cur:
            # 큰 표를 훑는 검사가 있어 기본 timeout으로는 부족하다.
            cur.execute("set statement_timeout to 180000")
            for name, sql, expected in CHECKS:
                try:
                    cur.execute(sql)
                    actual = int(cur.fetchone()[0])
                    status = "ok" if actual == expected else "fail"
                    detail = None
                except Exception as exc:  # noqa: BLE001 - 검사 하나가 나머지를 막지 않는다
                    conn.rollback()
                    cur.execute("set statement_timeout to 180000")
                    actual, status, detail = None, "error", f"{type(exc).__name__}: {exc}"
                results.append({
                    "check": name, "expected": expected,
                    "actual": actual, "status": status, "detail": detail,
                })
    finally:
        conn.close()

    failed = [r for r in results if r["status"] != "ok"]
    if args.json:
        print(json.dumps({"results": results, "failed": len(failed)},
                         ensure_ascii=False, indent=2))
        return 1 if failed else 0

    for row in results:
        mark = {"ok": "OK  ", "fail": "FAIL", "error": "ERR "}[row["status"]]
        line = f"  {mark} {row['check']:44s} got={row['actual']} want={row['expected']}"
        if row["detail"]:
            line += f"  {row['detail'][:80]}"
        print(line)
    print(f"\n데이터 불변식: 통과 {len(results) - len(failed)} / 실패 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
