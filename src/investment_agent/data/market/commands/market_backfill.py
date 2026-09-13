"""일봉·기업행위 과거 이력 복구. daily와 같은 수집 절차를 쓰고 대상·기간만 다르다."""
from __future__ import annotations

import argparse

from investment_agent.operations.backfill import add_backfill_from_arg, resolve_backfill_window
from investment_agent.platform.logging import get_logger
from investment_agent.data.market import BACKFILL_YEARS
from investment_agent.data.market.application.price_collection import collect_prices

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.data.market.commands.market_backfill")
    add_backfill_from_arg(parser)
    parser.add_argument(
        "--scope",
        choices=("missing", "all-current"),
        default="missing",
        help=(
            "missing seeds only securities with no rows; all-current re-fetches every "
            "current collection target to extend or repair existing history."
        ),
    )
    parser.add_argument(
        "--tickers",
        help="쉼표로 구분한 대상 ticker. 지정 시 --scope를 무시하고 해당 종목만 백필한다.",
    )
    return parser.parse_args(argv)


def _backfill_prices(lookback_days: int, scope: str, tickers: str | None = None) -> None:
    """계획을 한 번 고정한 뒤 받아 archive → 기업행위 병합 → 가격 저장 순으로 반영한다."""
    from investment_agent.data.market import persistence as store
    from investment_agent.data.market.domain.retention import compact_price_rows
    from investment_agent.data.market.infrastructure.archive import archive_daily_rows
    from investment_agent.data.market.infrastructure.sources.yahoo import download_ohlcv

    if tickers:
        targets = store.targets_for_tickers([t.strip() for t in tickers.split(",") if t.strip()])
    elif scope == "all-current":
        targets = store.price_targets()
    else:
        targets = store.missing_price_targets()
    if not targets:
        log.info("시세 백필 대상 0건 — skip (scope=%s)", scope)
        return
    log.info("시세 백필 대상: %d 종목 · scope=%s · lookback_days=%d", len(targets), scope, lookback_days)

    # 운영 DB용 compact 전에 공급자 원본 일봉을 보존한다. archive가 실패하면 DB 쓰기를
    # 시작하지 않아, 복구할 수 없는 축소만 남기지 않는다.
    batch = collect_prices(
        targets, lookback_days=lookback_days, download=download_ohlcv, archive=archive_daily_rows,
    )
    changed_actions = store.merge_actions(batch.actions)
    written = store.upsert_prices(compact_price_rows(batch.prices))
    log.info(
        "✅ 시세 백필: prices=%d actions=%d(changed=%d) × %d 종목",
        written, len(batch.actions), changed_actions, len(targets),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    price_window = resolve_backfill_window(
        args.backfill_from,
        default_years=BACKFILL_YEARS,
    )
    _backfill_prices(price_window.days, args.scope, args.tickers)

    from investment_agent.data.market.domain.retention import prune_history
    prune_history(today=price_window.end)
    log.info("완료 ✅ (scope=%s)", args.scope)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
