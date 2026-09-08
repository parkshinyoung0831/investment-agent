"""최근 기업 전체 또는 세그먼트 공시를 동기화하는 canonical 잡."""
from __future__ import annotations

import argparse
import os
import traceback
from functools import partial

from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.data.fundamentals.commands.sync_filings")
    parser.add_argument(
        "--content",
        choices=("company", "segments"),
        default="company",
        help="company=기업 전체 재무, segments=사업·지역·제품 지표",
    )
    parser.add_argument("--period", choices=("quarter", "annual"))
    parser.add_argument("--lookback-days", type=int)
    parser.add_argument("--watchlist-only", action="store_true")
    parser.add_argument(
        "--tickers",
        help="쉼표로 구분한 tracked ticker만 동기화한다 (복구·검증용).",
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="segments의 기존 daily_xbrl 공시를 다시 계산한다.",
    )
    parser.add_argument(
        "--skip-earnings-events",
        action="store_true",
        help="company 동기화 중 Item 2.02 실적 속보 탐색을 생략한다.",
    )
    args = parser.parse_args(argv)
    if args.content == "segments" and args.period is None:
        parser.error("--content segments에는 --period가 필요하다")
    if args.content == "company" and args.reprocess:
        parser.error("--reprocess는 --content segments에서만 사용할 수 있다")
    if args.watchlist_only and args.tickers:
        parser.error("--watchlist-only와 --tickers는 함께 사용할 수 없다")
    args.tickers = {
        ticker.strip().upper()
        for ticker in (args.tickers or "").split(",")
        if ticker.strip()
    }
    return args


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    try:
        from investment_agent.data.fundamentals.application.sync_recent_filings import (
            sync_company_filings,
            sync_segment_filings,
        )

        if args.content == "company":
            from investment_agent.data.fundamentals.application.detect_earnings_events import (
                detect_earnings_events_for_ticker,
            )
            from investment_agent.data.fundamentals.infrastructure.sec import companyfacts
            from investment_agent.data.fundamentals.infrastructure.sec import press_releases
            from investment_agent.data.fundamentals.infrastructure.supabase import (
                company_financials,
                earnings_events,
            )
            from investment_agent.data.fundamentals.infrastructure.yahoo_finance import (
                reported_earnings,
            )

            lookback_days = args.lookback_days or int(
                os.environ.get("FUNDAMENTALS_INDEX_LOOKBACK_DAYS", "7")
            )
            detector = None
            if not args.skip_earnings_events:
                detector = partial(
                    detect_earnings_events_for_ticker,
                    filing_source=companyfacts,
                    reported_source=reported_earnings,
                    press_release_source=press_releases,
                    repository=earnings_events,
                )
            metrics = sync_company_filings(
                source=companyfacts,
                repository=company_financials,
                lookback_days=lookback_days,
                watchlist_only=args.watchlist_only,
                target_tickers=args.tickers,
                earnings_event_detector=detector,
            )
        else:
            from investment_agent.data.fundamentals.application.backfill_history import (
                prune_segment_history,
            )
            from investment_agent.data.fundamentals.infrastructure.sec import filing_documents
            from investment_agent.data.fundamentals.infrastructure.supabase import segment_metrics

            lookback_days = args.lookback_days or int(
                os.environ.get("FUNDAMENTALS_SEGMENT_LOOKBACK_DAYS", "7")
            )
            metrics = sync_segment_filings(
                args.period,
                source=filing_documents,
                repository=segment_metrics,
                lookback_days=lookback_days,
                reprocess=args.reprocess,
                watchlist_only=args.watchlist_only,
                target_tickers=args.tickers,
            )
            if not metrics.get("failures"):
                metrics["retention"] = prune_segment_history(segment_metrics)
            unmapped = sorted(metrics.pop("unmapped_concepts", None) or [])
            if unmapped:
                log.warning(
                    "segments unmapped concepts=%d top=%s",
                    len(unmapped),
                    ", ".join(unmapped[:15]),
                )
        log.info("filing sync complete content=%s metrics=%s", args.content, metrics)
        return 1 if metrics.get("failures") else 0
    except Exception as exc:  # noqa: BLE001 - canonical CLI 경계
        log.error("filing sync failed: %s\n%s", exc, traceback.format_exc())
        return 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
