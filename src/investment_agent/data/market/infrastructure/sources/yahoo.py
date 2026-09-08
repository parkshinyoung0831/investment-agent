"""Yahoo Finance market-data adapter with strict coverage and price validation."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from investment_agent.data.market.domain.calendar import completed_bar_cutoff, market_today
from investment_agent.data.market.domain.price_repair import (
    is_split_ratio,
    normalize_split_adjusted_prices,
    validate_repaired_prices,
)
from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import network_retry

log = get_logger(__name__)

_OHLC_BOUND_REPAIR_REL_TOLERANCE = 0.005
@network_retry()
def _yf_download(tickers_str: str, start: str):
    """Download actions and daily bars; yfinance's own repair is the first pass."""
    return yf.download(
        tickers=tickers_str,
        start=start,
        interval="1d",
        auto_adjust=False,
        actions=True,
        repair=True,
        group_by="ticker",
        progress=False,
        threads=True,
        timeout=20,
    )


def _rows_from_frame(raw: pd.DataFrame | None, tickers: list[str]) -> list[dict]:
    """Convert one Yahoo batch response without hiding absent symbols."""
    if raw is None or raw.empty:
        return []
    # 1종목일 때도 다종목과 같은 형식으로 맞춤 (안 하면 신규 1종목이 조용히 0건 될 수 있음)
    if not isinstance(raw.columns, pd.MultiIndex):
        raw.columns = pd.MultiIndex.from_product([[tickers[0]], raw.columns])
    available = set(raw.columns.get_level_values(0))
    out: list[dict] = []
    for t in tickers:
        if t not in available:
            continue
        sub = raw[t].dropna(how="all", subset=["Close"])
        if sub.empty:
            continue
        for ts, r in sub.iterrows():
            div = r.get("Dividends")
            spl = r.get("Stock Splits")
            close = r.get("Close")
            adj_close = r.get("Adj Close")
            if close is None or pd.isna(close) or adj_close is None or pd.isna(adj_close):
                continue
            out.append({
                "ticker": t,
                "trade_date": (ts.date() if hasattr(ts, "date") else ts).isoformat(),
                "open":  None if pd.isna(r.get("Open"))  else float(r["Open"]),
                "high":  None if pd.isna(r.get("High"))  else float(r["High"]),
                "low":   None if pd.isna(r.get("Low"))   else float(r["Low"]),
                "close": float(close),
                "adj_close": float(adj_close),
                "volume": None if pd.isna(r.get("Volume")) else int(r["Volume"]),
                "div_amount":  None if not div or pd.isna(div) else float(div),
                "split_ratio": None if not spl or pd.isna(spl) else float(spl),
                "source": "yfinance",
            })
    return out


def _repair_small_ohlc_bound_errors(rows: list[dict]) -> list[dict]:
    """Expand Yahoo high/low for small open/close envelope inconsistencies.

    Yahoo occasionally publishes an opening or closing auction print just outside
    the reported intraday bounds.  A sub-0.5% discrepancy is deterministic to
    repair because the daily high/low must include both prints; larger differences
    remain untouched so validation fails closed as likely unit or parsing errors.
    """
    repaired: list[dict] = []
    for row in rows:
        current = dict(row)
        values = [current.get(name) for name in ("open", "high", "low", "close")]
        try:
            open_, high, low, close = (float(value) for value in values)
        except (TypeError, ValueError):
            repaired.append(current)
            continue
        if not all(math.isfinite(value) and value > 0 for value in (open_, high, low, close)):
            repaired.append(current)
            continue

        expected_high = max(open_, close)
        expected_low = min(open_, close)
        changed = False
        if high < expected_high:
            relative_gap = (expected_high - high) / expected_high
            if relative_gap <= _OHLC_BOUND_REPAIR_REL_TOLERANCE:
                current["high"] = expected_high
                changed = True
        if low > expected_low:
            relative_gap = (low - expected_low) / expected_low
            if relative_gap <= _OHLC_BOUND_REPAIR_REL_TOLERANCE:
                current["low"] = expected_low
                changed = True
        if changed:
            current["source"] = "yfinance_repaired"
        repaired.append(current)
    return repaired


def _exclude_unfinished_daily_bars(rows: list[dict], cutoff: date) -> list[dict]:
    """Drop provider rows newer than the conservative finalized-bar cutoff."""
    return [
        row
        for row in rows
        if date.fromisoformat(str(row["trade_date"])) <= cutoff
    ]


def _validate_price_rows(rows: list[dict], tickers: list[str]) -> None:
    contributed = {str(row["ticker"]) for row in rows}
    missing = sorted(set(tickers) - contributed)
    if missing:
        raise RuntimeError(
            "yfinance price coverage incomplete: "
            f"missing={missing[:20]} count={len(missing)}/{len(tickers)}"
        )

    duplicates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    invalid: list[tuple[str, str, str]] = []
    for row in rows:
        key = (str(row["ticker"]), str(row["trade_date"]))
        if key in seen:
            duplicates.append(key)
        seen.add(key)
        values = {
            name: row.get(name)
            for name in ("open", "high", "low", "close", "adj_close")
        }
        if any(
            value is None or not math.isfinite(float(value)) or float(value) <= 0
            for value in values.values()
        ):
            invalid.append((*key, "non-positive or missing OHLC"))
            continue
        open_, high, low, close = (
            float(values[name]) for name in ("open", "high", "low", "close")
        )
        if high < max(open_, low, close) or low > min(open_, high, close):
            invalid.append((*key, "incoherent OHLC"))
        volume = row.get("volume")
        if volume is None or int(volume) < 0:
            invalid.append((*key, "invalid volume"))
        dividend = row.get("div_amount")
        if dividend is not None and (
            not math.isfinite(float(dividend)) or float(dividend) < 0
        ):
            invalid.append((*key, "invalid div_amount"))
        split = row.get("split_ratio")
        if split is not None and (
            not math.isfinite(float(split))
            or float(split) <= 0
            or math.isclose(float(split), 1.0)
        ):
            invalid.append((*key, "invalid split_ratio"))
    if duplicates:
        raise RuntimeError(f"yfinance duplicate price keys: {duplicates[:10]}")
    if invalid:
        raise RuntimeError(f"yfinance invalid price rows: {invalid[:10]}")


def download_ohlcv(tickers: list[str], lookback_days: int) -> list[dict]:
    """Return validated, split-normalized daily bars for every requested ticker."""
    if not tickers:
        return []
    requested = list(dict.fromkeys(str(ticker) for ticker in tickers))
    start = (market_today() - timedelta(days=lookback_days)).isoformat()
    rows = _rows_from_frame(_yf_download(" ".join(requested), start), requested)

    # A successful HTTP response can still omit one symbol. Retry only omissions
    # individually so a transient partial batch cannot be persisted as success.
    contributed = {str(row["ticker"]) for row in rows}
    for ticker in sorted(set(requested) - contributed):
        rows.extend(_rows_from_frame(_yf_download(ticker, start), [ticker]))

    cutoff = completed_bar_cutoff()
    completed_rows = _exclude_unfinished_daily_bars(rows, cutoff)
    dropped = len(rows) - len(completed_rows)
    if dropped:
        log.info(
            "excluded %d unfinished daily bars newer than %s",
            dropped,
            cutoff,
        )
    rows = _repair_small_ohlc_bound_errors(completed_rows)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row["ticker"])].append(row)
    normalized = [
        row
        for ticker in requested
        for row in normalize_split_adjusted_prices(grouped.get(ticker, []))
    ]
    _validate_price_rows(normalized, requested)
    normalized_by_ticker: dict[str, list[dict]] = defaultdict(list)
    for row in normalized:
        normalized_by_ticker[str(row["ticker"])].append(row)
    for ticker, ticker_rows in normalized_by_ticker.items():
        actions = [
            {
                "action_date": str(row["trade_date"]),
                "split_ratio": float(row["split_ratio"]),
            }
            for row in ticker_rows
            if is_split_ratio(row.get("split_ratio"))
        ]
        try:
            validate_repaired_prices(ticker_rows, actions)
        except ValueError as exc:
            raise RuntimeError(
                f"yfinance split validation failed ticker={ticker}: {exc}"
            ) from exc
    log.info(
        "yfinance prices OK %d/%d tickers, %d rows",
        len({row["ticker"] for row in normalized}),
        len(requested),
        len(normalized),
    )
    return normalized

