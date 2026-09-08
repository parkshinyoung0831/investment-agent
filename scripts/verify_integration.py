"""실제 Supabase에 붙어 각 서브시스템의 조회 경로를 한 번씩 태워 보는 점검 도구.

    python scripts/verify_integration.py [--quiet]

`tests/`의 단위 테스트는 네트워크·DB를 때리지 않는 것이 이 저장소의 관례다. 그래서
스키마가 코드와 어긋나도 테스트는 초록이고, 그 간극은 운영에서 PGRST 404로만 드러난다.
이 스크립트가 그 간극을 메운다 — 스키마를 고치거나 DB를 재구축한 뒤에 돌린다.

읽기만 한다. 쓰기·발송·주문은 하지 않는다.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

Result = tuple[str, str, str]
RESULTS: list[Result] = []


def check(label: str, target) -> None:
    """조회 하나를 태워 보고 결과를 모은다.

    ``target``이 ``(module, "attr")`` 이면 속성을 **호출 시점에** 찾는다. 코드에서
    사라진 함수를 가리키는 점검이 남아 있을 때 인자 평가 단계에서 AttributeError로
    죽으면 나머지 점검이 통째로 묻힌다 — 그 누락이야말로 이 도구가 잡아야 할
    드리프트이므로, 크래시가 아니라 FAIL 한 줄로 보고한다.
    """
    try:
        if isinstance(target, tuple):
            module, attr = target
            fn = getattr(module, attr)
        else:
            fn = target
        value = fn()
        # DataResult는 예외를 던지지 않고 실패를 값으로 돌려준다. 그것을 OK로 세면
        # 이 도구가 잡으라고 만들어진 드리프트가 그대로 통과한다 — 실제로
        # `reporting.macro_measures`의 조회 불가가 그렇게 오래 숨어 있었다.
        status = getattr(value, "status", None)
        if status in {"error", "unconfigured", "blocked"}:
            RESULTS.append(("FAIL", label, f"{status}: {str(getattr(value, 'message', ''))[:120]}"))
            return
        if isinstance(value, (list, tuple, set, dict)):
            detail = f"{len(value)}건"
        else:
            detail = str(value)[:60]
        RESULTS.append(("OK", label, detail))
    except Exception as exc:  # noqa: BLE001 - 전부 모아 한 번에 보고한다
        RESULTS.append(("FAIL", label, f"{type(exc).__name__}: {str(exc)[:150]}"))


def run() -> int:
    now = datetime.now(timezone.utc)
    today = now.date()

    from investment_agent.data.universe.watchlists import db as alerts_db
    check("alerts.active_members", lambda: alerts_db.active_members("fundamentals"))
    check("alerts.list_members", (alerts_db, "list_members"))

    from investment_agent.data.universe import persistence as universe_db
    check("universe.select_entity_pending", (universe_db, "select_entity_pending"))
    check("universe.select_security_profiles", (universe_db, "select_security_profiles"))

    from investment_agent.data.market import persistence as market_db
    check("market.universe_tracked", (market_db, "universe_tracked"))
    check("market.universe_missing_prices", (market_db, "universe_missing_prices"))
    check("market.latest_price_date", (market_db, "latest_price_date"))

    from investment_agent.data.fundamentals.infrastructure.supabase import share_class_snapshots as shares
    check("fundamentals.load_shares_outstanding_by_cik",
          lambda: shares.load_shares_outstanding_by_cik("0000320193"))
    from investment_agent.data.fundamentals.infrastructure.supabase import company_financials as cf
    from investment_agent.data.fundamentals.infrastructure.supabase import expectations as exp
    from investment_agent.data.fundamentals.infrastructure.supabase import segment_metrics as seg
    check("fundamentals.tickers_by_cik", (cf, "tickers_by_cik"))
    check("fundamentals.last_filed_map", (cf, "last_filed_map"))
    check("fundamentals.ciks_missing_financials", (cf, "ciks_missing_financials"))
    check("fundamentals.watchlist_tickers", (cf, "watchlist_tickers"))
    check("segments.watchlist_tickers", (seg, "watchlist_tickers"))
    check("segments.existing_accessions", (seg, "existing_accessions"))
    check("segments.ciks_missing_segments", lambda: seg.ciks_missing_segments("quarter"))
    check("expectations.watchlist_tickers", (exp, "watchlist_tickers"))
    check("expectations.universe_tracked", (exp, "universe_tracked"))

    from investment_agent.platform.db.postgres import sb
    from investment_agent.reporting.notifications.macro import MacroNotificationStore
    from investment_agent.platform.db.postgres import Database
    macro_notify_store = MacroNotificationStore(Database(sb))
    check("notify.macro.load_core", (macro_notify_store, "load_core"))
    check("notify.macro.core_already_claimed",
          lambda: macro_notify_store.already_claimed(notification_key=f"core:{today.isoformat()}"))
    check("notify.macro.load_watch_pending", (macro_notify_store, "load_watch_pending"))

    from investment_agent.data.macro.releases import db as econ_db
    check("econ_calendar.enabled_series", (econ_db, "enabled_series"))
    check("econ_calendar.measures", (econ_db, "measures_by_series"))
    check("econ_calendar.primary_measures", (econ_db, "primary_measures"))

    from investment_agent.data.institutional import persistence as gurus_db
    check("gurus.get_active_manager_ciks", (gurus_db, "get_active_manager_ciks"))
    check("gurus.stored_accessions", (gurus_db, "stored_accessions"))
    check("gurus.get_identifier_cache", (gurus_db, "get_identifier_cache"))

    from investment_agent.notifications.earnings_calendar import candidates as ec_candidates
    from investment_agent.notifications.earnings_report import candidates as er_candidates
    from investment_agent.notifications.institutional import state as gurus_state
    check("notify.earnings_report.pending_state", (er_candidates, "pending_state"))
    check("notify.earnings_calendar.pending_state", (ec_candidates, "pending_state"))
    check("notify.gurus.pending_state", (gurus_state, "pending_state"))

    from investment_agent.operations.monitoring import counters
    check("ops.counters.collect", (counters, "collect"))

    from investment_agent.trading.supabase_repository import SupabaseRepository
    repo = SupabaseRepository()
    check("trading.current_tracked_tickers", (repo, "current_tracked_tickers"))
    check("trading.historical_sp500_membership",
          lambda: repo.historical_sp500_membership(
              start_date=today - timedelta(days=365), end_date=today))
    check("trading.candidate_tickers", lambda: repo.candidate_tickers(as_of_at=now, limit=5))
    check("trading.market_prices", lambda: repo.market_prices("AAPL", now, limit=10))
    check("trading.technical_snapshot", lambda: repo.technical_snapshot("AAPL", now))
    check("trading.fundamentals", lambda: repo.fundamentals("AAPL", now, limit=4))
    check("trading.estimates", lambda: repo.estimates("AAPL", now, limit=4))
    check("trading.macro_snapshot", lambda: repo.macro_snapshot(now))
    check("trading.segment_snapshot", lambda: repo.segment_snapshot("AAPL", now))
    check("trading.guru_snapshot", lambda: repo.guru_snapshot("AAPL", now))
    check("trading.econ_snapshot", lambda: repo.econ_snapshot(now))
    check("trading.latest_signal_batch_id",
          lambda: repo.latest_signal_batch_id(as_of_at=now))

    import inspect

    from investment_agent.dashboard import db as dash_db
    for name in sorted(dir(dash_db)):
        if not name.startswith("load_"):
            continue
        fn = getattr(dash_db, name)
        if not callable(fn):
            continue
        try:
            params = inspect.signature(fn).parameters.values()
        except (TypeError, ValueError):
            continue
        if any(p.default is inspect.Parameter.empty
               and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in params):
            continue  # 인자가 필요한 조회는 대시보드 화면에서만 의미가 있다
        check(f"dashboard.{name}", fn)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts/verify_integration.py")
    parser.add_argument("--quiet", action="store_true", help="실패한 항목만 출력")
    args = parser.parse_args(argv)

    run()
    failures = [row for row in RESULTS if row[0] == "FAIL"]
    stream = getattr(sys.stdout, "buffer", None)

    def emit(text: str) -> None:
        if stream is None:
            print(text)
            return
        stream.write(text.encode("utf-8", "replace") + b"\n")
        stream.flush()

    for status, label, detail in RESULTS:
        if args.quiet and status == "OK":
            continue
        emit(f"  {'OK  ' if status == 'OK' else 'FAIL'} {label:44s} {detail}")
    emit(f"\n연동 점검: 성공 {len(RESULTS) - len(failures)} / 실패 {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
