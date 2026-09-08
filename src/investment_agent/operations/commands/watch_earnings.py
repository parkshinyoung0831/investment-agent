"""발표 예정 세션에 맞춰 관심종목 공시만 좁게 훑는 canonical 잡.

로컬 하네스는 세션 창 안에서 이 잡을 짧은 주기로 반복 호출하고, GitHub Actions는
BMO·AMC가 끝난 뒤 고정 시각에 한 번씩 호출한다. 둘 다 같은 진입점을 쓰므로 수집
경로가 갈리지 않는다 — 경로가 갈리면 한쪽에서만 재현되는 버그가 생긴다.

중복은 두 겹으로 막는다.
1. 수집: `earnings_results`의 자연키(ticker, fiscal_year, fiscal_period, accession_no)가
   같은 8-K를 두 번 저장하지 않는다.
2. 발송: notification producer가 `notifications.outbox`에
   `(producer, notification_key)`를 먼저 선점한다. 먼저 기록한 쪽만 보낸다.
"""
from __future__ import annotations

import argparse
import time
import traceback
from datetime import datetime, timezone

from investment_agent.operations.runtime import run_log_payload
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)

WORKFLOW = "fundamentals_earnings_watch"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.watch_earnings")
    parser.add_argument(
        "--session",
        choices=("auto", "bmo", "amc", "any"),
        default="auto",
        help="auto는 현재 ET 시각으로 수집 창을 판정한다. any는 창 판정 없이 전 관심종목.",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="수집 뒤 미발송 속보를 바로 Discord로 보낸다(하네스 실시간 경로).",
    )
    parser.add_argument(
        "--report-notify",
        action="store_true",
        help="10-Q/K와 세그먼트 적재가 끝난 종목의 정밀 카드를 바로 보낸다.",
    )
    parser.add_argument(
        "--poll-attempts",
        type=int,
        default=1,
        help="대상이 있을 때 같은 종목을 재확인할 횟수(1~5, 기본 1).",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=60,
        help="재확인 간격 초(15~60, 기본 60).",
    )
    parser.add_argument("--dry-run", action="store_true", help="대상만 출력하고 끝낸다.")
    args = parser.parse_args(argv)
    if not 1 <= args.poll_attempts <= 5:
        parser.error("--poll-attempts는 1~5여야 합니다")
    if not 15 <= args.poll_interval_seconds <= 60:
        parser.error("--poll-interval-seconds는 15~60이어야 합니다")
    if args.report_notify and not args.notify:
        parser.error("--report-notify에는 --notify가 필요합니다")
    return args


def _targets(
    session: str,
    now: datetime,
) -> tuple[list[str], dict[str, list[str]], dict[str, list[str]]]:
    from investment_agent.data.fundamentals.application.select_session_targets import (
        select_session_targets,
    )
    from investment_agent.data.fundamentals.infrastructure.supabase import company_financials

    rows = company_financials.watchlist_expected_reports()
    if session == "any":
        tickers = sorted({str(r["ticker"]) for r in rows if r.get("ticker")})
        return tickers, {"any": tickers}, {"any": tickers}

    if session in ("bmo", "amc"):
        selected = select_session_targets(rows, now)
        picked = sorted(selected["by_session"].get(session, []))
        return picked, {session: picked}, {"session_safety_net": picked}

    from investment_agent.data.fundamentals.application.select_session_targets import (
        select_timed_targets,
    )

    selected = select_timed_targets(rows, now)
    return (
        selected["tickers"],
        selected["by_session"],
        selected["by_confidence"],
    )


def _sync_detected_reports(
    tickers: list[str],
    *,
    report_notify: bool,
) -> dict:
    """대상 종목의 10-Q/K를 즉시 적재하고 세그먼트를 준비한다.

    8-K는 보도자료 속보만으로 끝낼 수 있지만, 정밀 카드는 같은 accession의
    회사 전체·차원 재무가 모두 준비돼야 한다. 신규 10-Q/K가 없으면 submissions
    확인만 하고 즉시 끝난다.
    """
    from investment_agent.data.fundamentals.application.sync_recent_filings import (
        sync_company_filings,
        sync_segment_filings,
    )
    from investment_agent.data.fundamentals.infrastructure.sec import companyfacts
    from investment_agent.data.fundamentals.infrastructure.sec import filing_documents
    from investment_agent.data.fundamentals.infrastructure.supabase import (
        company_financials,
        segment_metrics,
    )

    target_set = set(tickers)
    company = sync_company_filings(
        source=companyfacts,
        repository=company_financials,
        watchlist_only=True,
        target_tickers=target_set,
        earnings_event_detector=None,
    )
    company_failures = list(company.get("failures") or [])
    if not company.get("filings"):
        return {
            "company": company,
            "segments": {},
            "report_ready": False,
            "failures": company_failures,
        }

    segment_results = {
        period: sync_segment_filings(
            period,
            source=filing_documents,
            repository=segment_metrics,
            watchlist_only=True,
            target_tickers=target_set,
        )
        for period in ("quarter", "annual")
    }
    segment_failures = [
        failure
        for result in segment_results.values()
        for failure in result.get("failures", [])
    ]
    failures = [*company_failures, *segment_failures]
    report_ready = not failures
    if report_notify and report_ready:
        try:
            import asyncio

            from investment_agent.notifications.earnings_report.run import run as send_report

            asyncio.run(send_report(tickers=target_set))
        except Exception as exc:
            log.exception("earnings watch: 정밀 카드 즉시 발송 실패")
            failures.append({"stage": "report_notify", "error": repr(exc)})
            report_ready = False
    return {
        "company": company,
        "segments": segment_results,
        "report_ready": report_ready,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    started = datetime.now(timezone.utc)
    clock = time.monotonic()
    try:
        from investment_agent.data.fundamentals.application.select_session_targets import (
            session_now,
        )
        from investment_agent.data.fundamentals.infrastructure.supabase import company_financials

        now = datetime.now(timezone.utc)
        tickers, by_session, by_confidence = _targets(args.session, now)
        log.info(
            "earnings watch targets session_now=%s selected=%d by_session=%s by_confidence=%s",
            session_now(now), len(tickers),
            {k: len(v) for k, v in by_session.items()},
            {k: len(v) for k, v in by_confidence.items()},
        )
        if args.dry_run:
            print("\n".join(tickers))
            return 0
        if not tickers:
            log.info("earnings watch: 지금 수집 창이 열린 관심종목 없음")
            return 0

        # (ticker, cik) 쌍이 필요하다. 관심종목만 좁혀 뽑는다.
        wanted = set(tickers)
        pairs = sorted(
            (str(row["ticker"]), str(row["cik"]))
            for row in company_financials.gating_universe()
            if row.get("cik") is not None and str(row.get("ticker")) in wanted
        )
        missing = wanted - {ticker for ticker, _ in pairs}
        static_failures: list[dict] = []
        if missing:
            log.error("earnings watch: CIK 없는 관심종목 %s", sorted(missing))
            static_failures.extend(
                {"ticker": ticker, "stage": "target_mapping", "error": "missing CIK"}
                for ticker in sorted(missing)
            )

        from investment_agent.data.fundamentals.application.detect_earnings_events import (
            detect_earnings_events,
        )
        from investment_agent.data.fundamentals.infrastructure.sec import companyfacts
        from investment_agent.data.fundamentals.infrastructure.sec import press_releases
        from investment_agent.data.fundamentals.infrastructure.supabase import earnings_events
        from investment_agent.data.fundamentals.infrastructure.yahoo_finance import reported_earnings

        total_metrics = {"rows": 0, "filings_discovered": 0}
        report_metrics: dict = {}
        attempt_history: list[dict] = []
        terminal_failures: list[dict] = []
        sent = 0
        for attempt in range(1, args.poll_attempts + 1):
            attempt_failures: list[dict] = []
            metrics = detect_earnings_events(
                pairs,
                filing_source=companyfacts,
                press_release_source=press_releases,
                repository=earnings_events,
                reported_source=reported_earnings,
            )
            total_metrics["rows"] += int(metrics.get("rows") or 0)
            total_metrics["filings_discovered"] += int(metrics.get("filings_discovered") or 0)
            attempt_failures.extend(metrics.get("failures") or [])

            if args.notify:
                # 패키지 __init__이 같은 이름의 run 함수를 재수출해 서브모듈을 가린다.
                from investment_agent.notifications.earnings_flash.run import run as send_flash

                try:
                    sent = send_flash(tickers=set(tickers))
                except Exception as exc:
                    log.exception("earnings watch: 속보 발송 실패")
                    attempt_failures.append(
                        {"stage": "flash_notify", "error": repr(exc)}
                    )

            report_metrics = _sync_detected_reports(
                tickers,
                report_notify=args.report_notify,
            )
            attempt_failures.extend(report_metrics.get("failures") or [])
            completed = bool(sent or report_metrics.get("company", {}).get("filings"))
            attempt_history.append({
                "attempt": attempt,
                "sent": sent,
                "report_filings": len(
                    report_metrics.get("company", {}).get("filings") or []
                ),
                "failures": attempt_failures,
            })
            terminal_failures = attempt_failures
            if completed and not attempt_failures:
                log.info(
                    "earnings watch: event 처리 완료 attempt=%d sent=%d reports=%d",
                    attempt,
                    sent,
                    attempt_history[-1]["report_filings"],
                )
                break
            if attempt < args.poll_attempts:
                time.sleep(args.poll_interval_seconds)

        failures = [*static_failures, *terminal_failures]
        log.info(
            "earnings watch complete %s",
            run_log_payload(
                workflow=WORKFLOW,
                status="failed" if failures else "success",
                rows_upserted=total_metrics["rows"],
                tickers_processed=len(pairs),
                duration_sec=round(time.monotonic() - clock, 3),
                started_at=started.isoformat(),
                detail={
                    "by_session": by_session,
                    "by_confidence": by_confidence,
                    "poll_attempts": args.poll_attempts,
                    "attempt_history": attempt_history,
                    "sent": sent,
                    "reports": report_metrics,
                    "failures": failures,
                },
            ),
        )
        return 1 if failures else 0
    except Exception as exc:  # noqa: BLE001 - canonical CLI 경계
        log.error("earnings watch failed: %s\n%s", exc, traceback.format_exc())
        return 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
