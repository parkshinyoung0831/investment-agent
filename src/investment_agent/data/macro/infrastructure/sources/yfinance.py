"""yfinance adapters with one batch request for price-like indicators."""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from investment_agent.data.macro.infrastructure.fetch import safe_fetch
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)
_NEW_YORK = ZoneInfo("America/New_York")


def _market_today() -> date:
    """yfinance info 값의 기준일을 뉴욕 날짜로 맞춘다."""
    return datetime.now(timezone.utc).astimezone(_NEW_YORK).date()

SPARSE_THRESHOLD = 60
_INFO_FIELD_MAP = {"per": "trailingPE", "fwd_per": "forwardPE", "pbr": "priceToBook"}


class YFinanceError(RuntimeError):
    """yfinance 수집 계약 위반의 공통 기반 예외."""


class YFinanceConfigurationError(YFinanceError):
    """ticker/field 설정이 잘못되었을 때 발생한다."""


class UnsupportedYFinanceFieldError(YFinanceConfigurationError):
    """허용 목록 밖 info field를 fail-closed로 거부한다."""


class YFinanceProviderError(YFinanceError):
    """yfinance 호출이 실패했다."""

    def __init__(self, ticker: str, operation: str, cause: Exception) -> None:
        self.ticker = ticker
        self.operation = operation
        self.cause_type = type(cause).__name__
        super().__init__(
            f"{ticker}: yfinance {operation} failed ({self.cause_type})"
        )


class YFinanceDataError(YFinanceError):
    """yfinance 응답이 저장 가능한 시계열 계약을 만족하지 않는다."""


def _via_ticker(ticker: str, start: date, end: date) -> pd.Series:
    try:
        df = yf.Ticker(ticker).history(
            start=str(start),
            end=str(end),
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:
        raise YFinanceProviderError(ticker, "Ticker.history", exc) from exc
    if not isinstance(df, pd.DataFrame):
        raise YFinanceDataError(
            f"{ticker}: Ticker.history returned {type(df).__name__}, expected DataFrame"
        )
    if df.empty or "Close" not in df.columns:
        return pd.Series(dtype=float)
    return df["Close"].dropna().sort_index()


def _via_download(ticker: str, start: date, end: date) -> pd.Series:
    try:
        df = yf.download(
            ticker,
            start=str(start),
            end=str(end),
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        raise YFinanceProviderError(ticker, "download", exc) from exc
    if not isinstance(df, pd.DataFrame):
        raise YFinanceDataError(
            f"{ticker}: download returned {type(df).__name__}, expected DataFrame"
        )
    if df.empty:
        return pd.Series(dtype=float)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return (
        df["Close"].dropna().sort_index()
        if "Close" in df.columns
        else pd.Series(dtype=float)
    )


def _fetch_one(ticker: str, start: date, end: date) -> pd.Series:
    days = max(1, (end - start).days)
    expected_market_rows = max(1, int(days * 5 / 7))
    sparse_threshold = min(SPARSE_THRESHOLD, max(2, int(expected_market_rows * 0.5)))

    history_error: YFinanceError | None = None
    try:
        series = _via_ticker(ticker, start, end)
    except YFinanceError as exc:
        history_error = exc
        cause_type = getattr(exc, "cause_type", type(exc).__name__)
        log.warning("%s: Ticker.history failed (%s)", ticker, cause_type)
        series = pd.Series(dtype=float)
    if len(series) >= sparse_threshold:
        return series

    log.warning("%s: Ticker.history sparse (%d); trying download", ticker, len(series))
    series = _via_download(ticker, start, end)
    if series.empty:
        if history_error is not None:
            raise history_error
        raise YFinanceDataError(f"{ticker}: yfinance returned an empty series")
    if len(series) < sparse_threshold:
        log.error("%s: final response sparse (%d)", ticker, len(series))
    return series


def _extract_batch_close(
    raw: pd.DataFrame,
    ticker: str,
    ticker_count: int,
) -> pd.Series:
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    if not isinstance(raw.columns, pd.MultiIndex):
        return (
            raw["Close"].dropna().sort_index()
            if ticker_count == 1 and "Close" in raw.columns
            else pd.Series(dtype=float)
        )

    level0 = set(raw.columns.get_level_values(0))
    level1 = set(raw.columns.get_level_values(1))
    if ticker in level0:
        frame = raw[ticker]
        return (
            frame["Close"].dropna().sort_index()
            if "Close" in frame.columns
            else pd.Series(dtype=float)
        )
    if ticker in level1 and "Close" in level0:
        return raw["Close"][ticker].dropna().sort_index()
    return pd.Series(dtype=float)


def _fetch_many(tickers: list[str], start: date, end: date) -> dict[str, pd.Series]:
    unique = list(dict.fromkeys(tickers))
    if not unique:
        return {}
    try:
        raw = yf.download(
            unique,
            start=str(start),
            end=str(end),
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:  # noqa: BLE001 - batch provider failure falls back per ticker
        # batch 장애는 아래 per-ticker fallback으로 복구한다. 원문 예외에는 URL이
        # 포함될 수 있어 로그에는 형식만 남긴다.
        log.warning("yfinance batch download failed: %s", type(exc).__name__)
        raw = pd.DataFrame()
    if not isinstance(raw, pd.DataFrame):
        log.warning(
            "yfinance batch returned invalid type: %s", type(raw).__name__
        )
        raw = pd.DataFrame()
    log.info("yfinance batch symbols=%d", len(unique))
    return {
        ticker: _extract_batch_close(raw, ticker, len(unique))
        for ticker in unique
    }


def _fetch_info_ratio(ticker: str, info_key: str) -> pd.Series:
    try:
        info = yf.Ticker(ticker).info
    except Exception as exc:
        raise YFinanceProviderError(ticker, "Ticker.info", exc) from exc
    if info is None:
        info = {}
    if not isinstance(info, dict):
        raise YFinanceDataError(
            f"{ticker}: yfinance info returned {type(info).__name__}, expected object"
        )
    value = info.get(info_key)
    if value is None:
        raise YFinanceDataError(f"{ticker}: yfinance info field {info_key} is missing")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise YFinanceDataError(
            f"{ticker}: yfinance info field {info_key} is non-numeric"
        ) from exc
    if not math.isfinite(numeric):
        raise YFinanceDataError(
            f"{ticker}: yfinance info field {info_key} is non-finite"
        )
    return pd.Series({pd.Timestamp(_market_today()).normalize(): numeric})


def _validate_result(ticker: str, series: pd.Series) -> pd.Series:
    """가격 응답을 저장 전에 검증한다."""
    if not isinstance(series, pd.Series):
        raise YFinanceDataError(
            f"{ticker}: yfinance returned {type(series).__name__}, expected Series"
        )
    try:
        cleaned = series.dropna().sort_index()
    except Exception as exc:
        raise YFinanceDataError(
            f"{ticker}: yfinance returned an invalid series"
        ) from exc
    if cleaned.empty:
        raise YFinanceDataError(f"{ticker}: yfinance returned an empty series")
    if not isinstance(cleaned.index, pd.DatetimeIndex):
        raise YFinanceDataError(
            f"{ticker}: yfinance returned a non-datetime index"
        )
    if cleaned.index.has_duplicates:
        raise YFinanceDataError(
            f"{ticker}: yfinance returned duplicate observation dates"
        )
    try:
        finite = all(math.isfinite(float(value)) for value in cleaned.values)
    except (TypeError, ValueError) as exc:
        raise YFinanceDataError(
            f"{ticker}: yfinance returned a non-numeric value"
        ) from exc
    if not finite:
        raise YFinanceDataError(
            f"{ticker}: yfinance returned a non-finite value"
        )
    return cleaned


def fetch_batch(
    indicators: list[dict],
    start: date,
    end: date,
) -> tuple[dict[str, pd.Series], list[dict]]:
    if start > end:
        raise YFinanceConfigurationError("start must be on or before end")

    price_tickers: list[str] = []
    for ind in indicators:
        raw_params = ind.get("source_params")
        params = {} if raw_params is None else raw_params
        # 잘못된 설정은 safe_fetch 안에서 해당 지표 실패로 기록한다. batch 준비가
        # 다른 정상 지표까지 중단해서는 안 된다.
        if not isinstance(params, dict) or params.get("field"):
            continue
        ticker = params.get("ticker") or ind.get("series_id")
        if isinstance(ticker, str) and ticker.strip():
            price_tickers.append(ticker)
    batch = _fetch_many(price_tickers, start, end)

    def _per(ind: dict) -> pd.Series:
        raw_params = ind.get("source_params")
        params = {} if raw_params is None else raw_params
        if not isinstance(params, dict):
            raise YFinanceConfigurationError("source_params must be an object")
        ticker = params.get("ticker") or ind["series_id"]
        if not isinstance(ticker, str) or not ticker.strip():
            raise YFinanceConfigurationError("yfinance ticker is required")
        field = params.get("field")
        if field:
            if not isinstance(field, str):
                raise YFinanceConfigurationError("yfinance field must be a string")
            info_key = _INFO_FIELD_MAP.get(field)
            if info_key is None:
                raise UnsupportedYFinanceFieldError(
                    f"unsupported yfinance field: {field}"
                )
            return _validate_result(ticker, _fetch_info_ratio(ticker, info_key))

        series = batch.get(ticker, pd.Series(dtype=float))
        if not series.empty:
            return _validate_result(ticker, series)
        log.warning("%s missing from batch; using per-ticker fallback", ticker)
        return _validate_result(ticker, _fetch_one(ticker, start, end))

    return safe_fetch(log, indicators, _per)
