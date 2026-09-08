"""MACRO 일별 증분 수집과 명시적 백필 진입점."""
from __future__ import annotations

import argparse
import math
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from investment_agent.config import load_config
from investment_agent.data.macro.infrastructure import settings
from investment_agent.data.macro.infrastructure.sources import ecos, fred, market, web, yfinance
from investment_agent.data.macro.domain.quality import audit_fx_cross_sources
from investment_agent.data.macro.repository import MacroRepository
from investment_agent.data.macro.application.refresh_market_state import refresh_macro
from investment_agent.data.universe.repository import UniverseRepository
from investment_agent.operations.backfill import add_backfill_from_arg
from investment_agent.operations.runtime import EXIT_FAILED, EXIT_OK, EXIT_PARTIAL, elapsed_sec, notify_ops
from investment_agent.platform.clock import utc_now
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)
FAIL_ALERT_THRESHOLD = 1


def _kst_today() -> date:
    """실행 위치와 무관하게 한국 기준 실행일을 반환한다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _build_row(series_id: str, timestamp, value: float) -> dict | None:
    if not math.isfinite(value):
        return None
    obs_date = timestamp.date() if hasattr(timestamp, "date") else timestamp
    obs_str = obs_date.isoformat() if hasattr(obs_date, "isoformat") else str(obs_date)
    return {"series_id": series_id, "obs_date": obs_str, "value": float(value)}


def _incremental_cutoff(
    frequency: str,
    end: date,
    *,
    daily_lookback_days: int = settings.DAILY_LOOKBACK_DAYS,
) -> date:
    """주기별 overlap 재조회 시작일을 반환한다."""
    days = (
        daily_lookback_days
        if frequency == "daily"
        else settings.INCREMENTAL_LOOKBACK_DAYS.get(frequency, daily_lookback_days)
    )
    return end - timedelta(days=days)


def _rows_for_series(
    series_id: str,
    series: pd.Series,
    *,
    cutoff: date,
    end: date,
) -> list[dict]:
    """겹침 구간의 시계열을 저장 후보 행으로 변환한다."""
    if not isinstance(series, pd.Series):
        raise TypeError(f"{series_id}: source returned {type(series).__name__}")
    cleaned = series.dropna().sort_index()
    if cleaned.empty:
        return []
    output: list[dict] = []
    seen_dates: set[str] = set()
    cutoff_ts = pd.Timestamp(cutoff)
    end_ts = pd.Timestamp(end)
    for timestamp, value in cleaned.items():
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        if ts < cutoff_ts or ts > end_ts:
            continue
        row = _build_row(series_id, ts, float(value))
        if row is None:
            continue
        if row["obs_date"] in seen_dates:
            raise ValueError("source returned duplicate observation dates")
        seen_dates.add(row["obs_date"])
        output.append(row)
    return output


def _failure(series_id: str, error: Exception) -> dict[str, str]:
    return {"series_id": series_id, "error": str(error), "type": type(error).__name__}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.data.macro.commands.macro_refresh")
    add_backfill_from_arg(parser, aliases=("--save-from",))
    parser.add_argument("--lookback-days", type=int)
    parser.add_argument("--series", action="append", default=None, metavar="SERIES_ID")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.lookback_days is not None and args.lookback_days < 1:
        parser.error("--lookback-days must be at least 1")
    try:
        save_cutoff = date.fromisoformat(args.backfill_from) if args.backfill_from else None
    except ValueError:
        parser.error("--backfill-from must be YYYY-MM-DD")
    only = {str(value).strip().upper() for value in (args.series or []) if str(value).strip()}

    configure_logging()
    t0 = time.monotonic()
    end = _kst_today()
    if save_cutoff is not None and save_cutoff > end:
        parser.error("--backfill-from cannot be in the future")
    mode = "backfill" if save_cutoff is not None else "daily"
    lookback_days = args.lookback_days or (
        settings.BACKFILL_WARMUP_DAYS if mode == "backfill" else settings.DAILY_LOOKBACK_DAYS
    )
    start = (
        save_cutoff - timedelta(days=lookback_days)
        if save_cutoff is not None
        else end - timedelta(days=lookback_days)
    )

    try:
        db = Database.from_config(load_config())
        macro_repo = MacroRepository(db)
        catalog = macro_repo.market_catalog()
    except Exception:  # noqa: BLE001 - 카탈로그/연결 실패를 실행 결과로 기록한다.
        log.exception("macro catalog load failed")
        if not args.dry_run:
            notify_ops("macro catalog load failed", logger=log)
        return EXIT_FAILED

    if only:
        known = {str(row["series_id"]).upper() for row in catalog}
        unknown = only - known
        if unknown:
            parser.error(f"unknown series: {', '.join(sorted(unknown))}")
        catalog = [row for row in catalog if str(row["series_id"]).upper() in only]

    universe_repo = UniverseRepository(db)
    market_reader = market.MarketPriceReader(db)
    adapters = {
        "fred": fred.fetch_batch,
        "ecos": ecos.fetch_batch,
        "yfinance": yfinance.fetch_batch,
        "web_crawling": web.fetch_batch,
        "market": market.fetch_batch,
    }

    def fetch_source(
        source: str,
        indicators: list[dict],
        fetch_start: date,
        fetch_end: date,
    ) -> tuple[dict[str, pd.Series], list[dict]]:
        source_start = (
            fetch_start
            if mode == "backfill"
            else min(
                _incremental_cutoff(
                    str(indicator.get("frequency") or "daily"),
                    fetch_end,
                    daily_lookback_days=lookback_days,
                )
                for indicator in indicators
            )
        )
        adapter = adapters.get(source)
        if adapter is None:
            error = ValueError(f"unsupported macro source: {source}")
            return {}, [_failure(str(indicator["series_id"]), error) for indicator in indicators]
        try:
            if source == "market":
                return adapter(
                    indicators,
                    source_start,
                    fetch_end + timedelta(days=1),
                    universe_repository=universe_repo,
                    load_prices=market_reader.rows,
                )
            return adapter(indicators, source_start, fetch_end + timedelta(days=1))
        except Exception as exc:  # noqa: BLE001 - source별 부분 성공을 보존한다.
            log.warning("macro source failed: source=%s error=%s", source, exc)
            return {}, [_failure(str(indicator["series_id"]), exc) for indicator in indicators]

    def validate(values: dict[str, pd.Series]) -> list[dict]:
        return audit_fx_cross_sources(values, fred._fetch_one, start=start, end=end)

    try:
        result = refresh_macro(
            db,
            catalog=catalog,
            start=start,
            end=end,
            collected_at=utc_now(),
            fetch=fetch_source,
            validate=validate,
            persist=not args.dry_run,
        )
    except Exception:  # noqa: BLE001 - 저장 실패는 성공으로 위장하지 않는다.
        log.exception("macro refresh failed")
        if not args.dry_run:
            notify_ops("macro refresh failed", logger=log)
        return EXIT_FAILED

    if result.failures and not args.dry_run and len(result.failures) >= FAIL_ALERT_THRESHOLD:
        notify_ops(f"macro partial: {len(result.failures)} failures", logger=log)
    log.info(
        "macro done: mode=%s series=%d observations=%d failures=%d duration_sec=%.1f",
        mode,
        result.series,
        result.observations,
        len(result.failures),
        elapsed_sec(t0),
    )
    return EXIT_PARTIAL if result.failures else EXIT_OK


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
