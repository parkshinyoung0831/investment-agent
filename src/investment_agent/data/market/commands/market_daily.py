"""Incremental daily market ingestion for current S&P 500 members."""
from __future__ import annotations

import argparse
import math
import time
from datetime import date, datetime, timedelta
from numbers import Number
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
from investment_agent.data.market.domain.price_repair import is_split_ratio

log = get_logger(__name__)

_PRICE_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "is_repaired",
)


def _same_value(left, right) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, Number) and isinstance(right, Number):
        return math.isclose(float(left), float(right), rel_tol=1e-10, abs_tol=1e-10)
    return str(left) == str(right)


def _prune_history_without_failing_ingest(today: date) -> None:
    """보존 정리는 실패해도 그날의 수집 결과를 되돌리지 않는다.

    정리는 이미 저장한 가격을 다듬는 뒷정리이고, 가격 수집 결과와 독립적으로
    재시도할 수 있어야 한다. 따라서 보존 정리 실패는 수집 성공을 뒤집지 않는다.

    그래도 조용히 삼키지는 않는다. 상세는 실행 로그에 남기고 Discord 시스템 로그에
    구조화된 경고 카드를 보내 다음 실행에서 다시 확인할 수 있게 한다.
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


def changed_rows(
    rows: list[dict],
    existing: dict[tuple[str, str], dict],
    *,
    date_key: str,
    compare_fields: tuple[str, ...],
) -> list[dict]:
    """Return only rows whose unique key is new or whose persisted value changed."""
    changed: list[dict] = []
    for row in rows:
        key = (str(row["ticker"]), str(row[date_key]))
        current = existing.get(key)
        if current is None or any(
            not _same_value(row.get(field), current.get(field))
            for field in compare_fields
        ):
            changed.append(row)
    return changed


def extract_split_events(raw_rows: list[dict]) -> list[dict]:
    """수집된 원천 가격 행에서 분할 이벤트를 추출한다."""
    actions: dict[tuple[str, str], dict] = {}
    for row in raw_rows:
        ratio = row.get("split_ratio")
        if not is_split_ratio(ratio):
            continue
        ticker = str(row["ticker"])
        action_date = str(row["trade_date"])
        key = (ticker, action_date)
        split_r = float(ratio)
        actions[key] = {
            "ticker": ticker,
            "action_date": action_date,
            "split_ratio": split_r,
            "source": row.get("source", "yfinance"),
        }
    return [actions[key] for key in sorted(actions)]


def extract_dividend_events(raw_rows: list[dict]) -> list[dict]:
    """수집된 원천 가격 행에서 배당 이벤트를 추출한다."""
    divs: dict[tuple[str, str], dict] = {}
    for row in raw_rows:
        amount = row.get("div_amount")
        if amount is None:
            continue
        try:
            val = float(amount)
            if val <= 0:
                continue
        except (TypeError, ValueError):
            continue
        ticker = str(row["ticker"])
        ex_date = str(row["trade_date"])
        key = (ticker, ex_date)
        divs[key] = {
            "ticker": ticker,
            "ex_date": ex_date,
            "div_amount": val,
            "source": row.get("source", "yfinance"),
        }
    return [divs[key] for key in sorted(divs)]


def clean_price_row(row: dict) -> dict:
    """market.prices_daily 저장용으로 배당·분할을 제외한 OHLCV 행을 만든다."""
    return {
        "ticker": str(row["ticker"]),
        "trade_date": str(row["trade_date"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": int(row.get("volume") or 0),
        "is_repaired": str(row.get("source") or "yfinance") == "yfinance_repaired",
    }


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

    from investment_agent.data.market.persistence import (
        latest_price_date,
        prices_since,
        select_split_events,
        universe_tracked,
        upsert_dividend_events,
        upsert_prices,
        upsert_split_events,
    )
    from investment_agent.data.market.infrastructure.sources.yahoo import download_ohlcv

    t0 = time.monotonic()
    today = datetime.now(ZoneInfo("America/New_York")).date()
    since = (today - timedelta(days=args.lookback_days)).isoformat()
    tickers = universe_tracked()
    log.info(
        "market daily start: targets=%d lookback_days=%d db_latest=%s",
        len(tickers),
        args.lookback_days,
        latest_price_date(),
    )
    if not tickers:
        raise RuntimeError("is_tracked=true returned no rows; run universe monthly first")

    raw_rows = download_ohlcv(tickers, lookback_days=args.lookback_days)
    if not raw_rows:
        raise RuntimeError(
            f"yfinance returned no price rows for {len(tickers)} tracked tickers"
        )

    # 1. 분할 이벤트 추출 및 저장
    split_events = extract_split_events(raw_rows)
    # 2. 배당 이벤트 추출 및 저장
    dividend_events = extract_dividend_events(raw_rows)

    # 3. OHLCV 행 정규화 및 변경사항 필터링
    clean_prices = [clean_price_row(r) for r in raw_rows]
    price_writes = changed_rows(
        clean_prices,
        prices_since(since),
        date_key="trade_date",
        compare_fields=_PRICE_FIELDS,
    )

    if not args.dry_run:
        existing_splits = {
            (r["ticker"], r["action_date"])
            for r in select_split_events(tickers)
        }
        new_split_tickers = {
            r["ticker"]
            for r in split_events
            if (r["ticker"], r["action_date"]) not in existing_splits
        }

        # 분할 이력은 이벤트를 기록하기 전에 전부 다운로드·검증한다. 여기서 실패하면
        # 이벤트가 미처리 상태로 남아 다음 실행이 같은 백필을 다시 시도할 수 있다.
        full_history_by_key: dict[tuple[str, str], dict] = {}
        for split_ticker in sorted(new_split_tickers):
            log.info("New split detected for %s; preparing full price history", split_ticker)
            rebackfill_rows = download_ohlcv(
                [split_ticker],
                lookback_days=BACKFILL_YEARS * 366,
            )
            if not rebackfill_rows:
                raise RuntimeError(
                    f"split price re-backfill returned no rows for {split_ticker}"
                )
            for row in rebackfill_rows:
                clean = clean_price_row(row)
                full_history_by_key[(clean["ticker"], clean["trade_date"])] = clean

        # 최근 행과 전체 백필 행을 한 번에 멱등 저장한다. 전체 이력이 성공한 뒤에만
        # 분할 이벤트를 기록하므로 DB 쓰기 실패도 다음 실행에서 재시도된다.
        writes_by_key = {
            (row["ticker"], row["trade_date"]): row
            for row in price_writes
        }
        writes_by_key.update(full_history_by_key)
        price_writes = [writes_by_key[key] for key in sorted(writes_by_key)]
        upsert_prices(price_writes)
        if split_events:
            upsert_split_events(split_events)
        if dividend_events:
            upsert_dividend_events(dividend_events)

        _prune_history_without_failing_ingest(today)

    log.info(
        "market daily done: price_candidates=%d price_writes=%d "
        "splits=%d dividends=%d dry_run=%s duration_sec=%.1f",
        len(clean_prices),
        len(price_writes),
        len(split_events),
        len(dividend_events),
        args.dry_run,
        elapsed_sec(t0),
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
