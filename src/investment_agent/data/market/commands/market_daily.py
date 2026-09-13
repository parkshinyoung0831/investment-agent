"""현재 수집 대상의 일봉 증분 수집. 최근 겹침 기간만 받고 바뀐 행만 쓴다."""
from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from investment_agent.operations.runtime import elapsed_sec, notify_ops
from investment_agent.platform.logging import get_logger
from investment_agent.operations.monitoring.incidents import (
    build_incident_embed,
    build_runtime_incident,
    current_github_run_url,
)
from investment_agent.data.market import (
    BACKFILL_YEARS,
    DAILY_ROLLING_DAYS,
)
from investment_agent.data.market.application.price_collection import (
    changed_prices,
    collect_prices,
)

log = get_logger(__name__)


def _prune_history_without_failing_ingest(today: date) -> None:
    """보존 정리는 실패해도 그날의 수집 결과를 되돌리지 않는다.

    정리는 이미 저장한 가격을 다듬는 뒷정리이고, 가격 수집 결과와 독립적으로
    재시도할 수 있어야 한다. 그래도 조용히 삼키지는 않는다 — 실행 로그와 Discord
    시스템 로그에 남겨 다음 실행에서 다시 확인하게 한다.
    """
    from investment_agent.data.market.domain.retention import prune_history

    try:
        prune_history(today=today)
    except Exception as exc:  # noqa: BLE001 - 수집 결과를 지키는 것이 우선이다
        log.warning("market retention failed (수집은 유지): %s: %s", type(exc).__name__, exc)
        incident = build_runtime_incident(
            workflow="market_daily",
            step="가격 이력 보존 정리",
            summary=f"{type(exc).__name__}: {exc}",
            conclusion="warning",
            impact="오늘 가격 수집은 유지됐지만 오래된 가격 이력 정리가 다음 실행으로 미뤄졌어요.",
            action="GitHub Actions 원문 로그에서 보존 정리 쿼리와 Supabase 제한 시간을 확인해 주세요.",
            url=current_github_run_url(),
        )
        notify_ops("", logger=log, embeds=[build_incident_embed(incident)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.data.market.commands.market_daily")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DAILY_ROLLING_DAYS,
        help="Overlapping calendar window used to recover late or missed rows.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and compare rows without writing to Supabase.",
    )
    args = parser.parse_args(argv)
    if args.lookback_days < 1:
        parser.error("--lookback-days must be at least 1")

    from investment_agent.data.market import persistence as store
    from investment_agent.data.market.infrastructure.sources.yahoo import download_ohlcv

    t0 = time.monotonic()
    today = datetime.now(ZoneInfo("America/New_York")).date()
    since = (today - timedelta(days=args.lookback_days)).isoformat()
    targets = store.price_targets()
    log.info(
        "market daily start: targets=%d lookback_days=%d db_latest=%s",
        len(targets), args.lookback_days, store.latest_price_date(),
    )
    if not targets:
        raise RuntimeError("is_tracked=true returned no rows; run universe monthly first")

    batch = collect_prices(targets, lookback_days=args.lookback_days, download=download_ohlcv)
    price_writes = changed_prices(batch.prices, store.prices_since(since))
    actions = batch.actions

    if not args.dry_run:
        known_splits = store.split_keys([target.security_id for target in targets])
        new_split_ids = {
            int(row["security_id"]) for row in actions
            if "split_ratio" in row and (int(row["security_id"]), str(row["action_date"])) not in known_splits
        }
        # 새 분할은 그 종목의 보관 기간 전체를 새 조정 기준으로 다시 받는다. 받기·검증을
        # 기업행위 기록보다 먼저 끝내므로, 도중에 실패하면 다음 실행이 같은 재수집을 다시 한다.
        writes = {(int(row["security_id"]), str(row["trade_date"])): row for row in price_writes}
        for target in [t for t in targets if t.security_id in new_split_ids]:
            log.info("new split detected for %s (%d); re-collecting full history", target.symbol, target.security_id)
            history = collect_prices([target], lookback_days=BACKFILL_YEARS * 366, download=download_ohlcv)
            writes.update({(int(row["security_id"]), str(row["trade_date"])): row for row in history.prices})
        price_writes = [writes[key] for key in sorted(writes)]
        store.upsert_prices(price_writes)
        store.merge_actions(actions)
        _prune_history_without_failing_ingest(today)

    log.info(
        "market daily done: price_candidates=%d price_writes=%d actions=%d dry_run=%s duration_sec=%.1f",
        len(batch.prices), len(price_writes), len(actions), args.dry_run, elapsed_sec(t0),
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
