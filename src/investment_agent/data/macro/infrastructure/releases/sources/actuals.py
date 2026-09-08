"""ECON raw actual provider adapters.

공통 계약(시간 제한, retry, rate limit, finite/duplicate 검증, provenance)은 여기서
강제한다. 각 provider의 parsing은 작은 전용 함수로 남겨 거대한 generic parser가
되지 않게 한다. ISM/AAII/placeholder endpoint는 의도적으로 없다.
"""
from __future__ import annotations

import math
import os
import threading
import time as wall_time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests

from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import retry_on_5xx

log = get_logger(__name__)
_FRED = "https://api.stlouisfed.org/fred/series/observations"
_ECOS = "https://ecos.bok.or.kr/api/StatisticSearch"
_EIA = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
_ECOS_PAGE_SIZE = 1000
_ECOS_MAX_PAGES = 100
_FRED_MIN_INTERVAL_SECONDS = 0.55  # FRED public API: maximum two requests/second.
_fred_lock = threading.Lock()
_fred_next_request = 0.0


class ActualsError(RuntimeError):
    """실제값 수집 계약 위반의 공통 기반 예외."""


class ActualConfigurationError(ActualsError):
    """DB source contract가 지원하는 모양이 아닐 때 발생한다."""


class UnsupportedActualSourceError(ActualConfigurationError):
    """허가되지 않았거나 구현되지 않은 source를 fail-closed로 막는다."""


class ActualProviderError(ActualsError):
    """원본 URL·키를 노출하지 않는 provider 오류."""

    def __init__(self, series_id: str, source: str, cause: Exception) -> None:
        self.series_id = series_id
        self.source = source
        self.cause_type = type(cause).__name__
        super().__init__(f"{series_id}: {source} provider failed ({self.cause_type})")


class ActualDataError(ActualsError):
    """provider payload가 ECON raw observation 계약을 어겼을 때 발생한다."""


class ActualNotAvailableYetError(ActualDataError):
    """요청 window에 아직 발표된 관측값이 없음을 나타낸다."""


def _fred_slot() -> None:
    global _fred_next_request
    with _fred_lock:
        now = wall_time.monotonic()
        wait = max(0.0, _fred_next_request - now)
        _fred_next_request = max(now, _fred_next_request) + _FRED_MIN_INTERVAL_SECONDS
    if wait:
        wall_time.sleep(wait)


@retry_on_5xx()
def _fred(fred_id: str, start: date, end: date) -> pd.Series:
    _fred_slot()
    response = requests.get(
        _FRED,
        params={
            "series_id": fred_id,
            "api_key": os.environ["FRED_API_KEY"],
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        },
        timeout=30,
    )
    response.raise_for_status()
    values = pd.Series(
        {
            pd.Timestamp(row["date"]): float(row["value"])
            for row in response.json().get("observations", [])
            if row.get("value") not in (None, "", ".")
        },
        dtype=float,
    )
    # 빈 dict는 pandas가 일반 Index를 만들므로, empty도 provider 계약의
    # DatetimeIndex 형태를 유지해 "아직 없음"과 malformed payload를 구분한다.
    if not isinstance(values.index, pd.DatetimeIndex):
        values.index = pd.DatetimeIndex(values.index)
    return values.sort_index()


def _ecos_token(frequency: str) -> str:
    return {"monthly": "M", "quarterly": "Q", "weekly": "W"}.get(frequency, "D")


def _ecos_period(day: date, frequency: str) -> str:
    if frequency == "monthly":
        return day.strftime("%Y%m")
    if frequency == "quarterly":
        return f"{day.year}Q{(day.month - 1) // 3 + 1}"
    return day.strftime("%Y%m%d")


@retry_on_5xx()
def _ecos(statistic: str, item: str, frequency: str, start: date, end: date) -> pd.Series:
    api_key = (os.environ.get("ECOS_API_KEY") or "").strip()
    if not api_key:
        raise ActualConfigurationError("ECOS_API_KEY is not configured")
    values: dict[pd.Timestamp, float] = {}
    offset, expected_count = 1, None
    for _ in range(_ECOS_MAX_PAGES):
        url = (
            f"{_ECOS}/{api_key}/json/kr/{offset}/{offset + _ECOS_PAGE_SIZE - 1}/"
            f"{statistic}/{_ecos_token(frequency)}/{_ecos_period(start, frequency)}/"
            f"{_ecos_period(end, frequency)}/{item}"
        )
        response = requests.get(url, headers={"User-Agent": "investment-agent-econ/2.0"}, timeout=30)
        response.raise_for_status()
        payload = response.json()
        block = payload.get("StatisticSearch")
        if not isinstance(block, dict):
            code = str((payload.get("RESULT") or {}).get("CODE") or "unknown")
            if code == "INFO-200" and offset == 1:
                raise ActualNotAvailableYetError("ECOS returned INFO-200 (no observation yet)")
            raise ActualDataError(f"ECOS returned {code} for requested series")
        rows = block.get("row") or []
        if not isinstance(rows, list) or len(rows) > _ECOS_PAGE_SIZE:
            raise ActualDataError("ECOS returned an invalid page")
        count = block.get("list_total_count")
        if count is not None:
            try:
                count = int(count)
            except (TypeError, ValueError) as exc:
                raise ActualDataError("ECOS returned an invalid total count") from exc
            if count < 0 or count > _ECOS_PAGE_SIZE * _ECOS_MAX_PAGES:
                raise ActualDataError("ECOS total count exceeds the bounded history window")
            if expected_count is not None and count != expected_count:
                raise ActualDataError("ECOS total count changed while paging")
            expected_count = count
        if expected_count is None and len(rows) == _ECOS_PAGE_SIZE:
            raise ActualDataError("ECOS full page is missing its total count")
        for row in rows:
            token = str(row.get("TIME") or "")
            raw_value = row.get("DATA_VALUE")
            if not token or raw_value in (None, ""):
                continue
            if frequency == "monthly":
                stamp = pd.Period(token, freq="M").end_time.normalize()
            elif frequency == "quarterly":
                stamp = pd.Period(token, freq="Q").end_time.normalize()
            else:
                stamp = pd.to_datetime(token)
            if stamp in values:
                raise ActualDataError("ECOS returned overlapping observation dates")
            values[stamp] = float(raw_value)
        fetched_count = offset - 1 + len(rows)
        if expected_count is None or fetched_count == expected_count:
            break
        if not rows or fetched_count > expected_count:
            raise ActualDataError("ECOS history ended before its declared total count")
        offset += len(rows)
    else:
        raise ActualDataError("ECOS history exceeded its page limit")
    result = pd.Series(values, dtype=float)
    if not isinstance(result.index, pd.DatetimeIndex):
        result.index = pd.DatetimeIndex(result.index)
    return result.sort_index()


@retry_on_5xx()
def _eia(series_code: str, start: date, end: date) -> pd.Series:
    response = requests.get(
        _EIA,
        params={
            "api_key": os.environ["EIA_API_KEY"],
            "frequency": "weekly",
            "data[0]": "value",
            "facets[series][]": series_code,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": 5000,
        },
        timeout=30,
    )
    response.raise_for_status()
    rows = (response.json().get("response") or {}).get("data") or []
    values = pd.Series(
        {
            pd.Timestamp(row["period"]): float(row["value"])
            for row in rows
            if row.get("period") and row.get("value") not in (None, "")
        },
        dtype=float,
    )
    if not isinstance(values.index, pd.DatetimeIndex):
        values.index = pd.DatetimeIndex(values.index)
    return values.sort_index()


def _fed_net_liquidity(start: date, end: date) -> pd.Series:
    """WALCL - TGA - ON RRP; 모든 결과는 USD billions."""
    walcl = _fred("WALCL", start, end)
    tga = _fred("WTREGEN", start, end)
    rrp = _fred("RRPONTSYD", start, end)
    index = walcl.index.union(tga.index).union(rrp.index).sort_values()
    values = (
        walcl.reindex(index).ffill()
        - tga.reindex(index).ffill()
        - rrp.reindex(index).ffill() * 1000.0
    ) / 1000.0
    return values.reindex(walcl.index).dropna()


def _contract(setting: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    source = str(setting.get("actual_provider") or "")
    contract = setting.get("source_contract") or {}
    actual = contract.get("actual") or {}
    if not source or not isinstance(actual, dict):
        raise ActualConfigurationError(f"{setting.get('series_id')}: incomplete actual contract")
    return source, actual


def _one(setting: dict[str, Any], start: date, end: date) -> pd.Series:
    """한 family의 raw value series. 설정 오류는 바로 type-preserving으로 낸다."""
    if start > end:
        raise ActualConfigurationError("start must be on or before end")
    series_id = str(setting.get("series_id") or "<unknown>")
    source, actual = _contract(setting)
    try:
        if source == "fred":
            code = str(actual.get("code") or "")
            if not code:
                raise ActualConfigurationError(f"{series_id}: fred code is required")
            values = _fred(code, start, end)
        elif source == "ecos":
            statistic, item = str(actual.get("statistic") or ""), str(actual.get("item") or "")
            if not statistic or not item:
                raise ActualConfigurationError(f"{series_id}: ECOS statistic/item is required")
            values = _ecos(statistic, item, str(setting["frequency"]), start, end)
        elif source == "eia":
            code = str(actual.get("series") or "")
            if not code:
                raise ActualConfigurationError(f"{series_id}: EIA series is required")
            values = _eia(code, start, end)
        elif source == "fred_components":
            values = _fed_net_liquidity(start, end)
        elif source == "unsupported":
            raise UnsupportedActualSourceError(f"{series_id}: source contract is unsupported")
        else:
            raise UnsupportedActualSourceError(f"{series_id}: unsupported actual provider {source}")
    except ActualsError:
        raise
    except Exception as exc:
        raise ActualProviderError(series_id, source, exc) from exc

    scale = actual.get("scale")
    if scale is not None:
        try:
            values = values * float(scale)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ActualConfigurationError(f"{series_id}: actual scale must be numeric") from exc
    return _validated(series_id, values)


def _validated(series_id: str, values: pd.Series) -> pd.Series:
    if not isinstance(values, pd.Series) or not isinstance(values.index, pd.DatetimeIndex):
        raise ActualDataError(f"{series_id}: provider returned an invalid time series")
    values = values.dropna().sort_index()
    if values.empty:
        raise ActualNotAvailableYetError(f"{series_id}: no observation in requested window")
    if values.index.has_duplicates:
        raise ActualDataError(f"{series_id}: provider returned duplicate observation dates")
    try:
        if not all(math.isfinite(float(value)) for value in values.values):
            raise ActualDataError(f"{series_id}: provider returned a non-finite value")
    except (TypeError, ValueError) as exc:
        raise ActualDataError(f"{series_id}: provider returned a non-numeric value") from exc
    return values


def fetch_batch(
    settings: list[dict[str, Any]],
    *,
    start: date,
    end: date,
    starts_by_series: dict[str, date] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """family별 raw observations. source 하나의 실패는 다른 family를 중단시키지 않는다.

    FRED 공개 rate limit을 지키기 위해 provider 호출은 순차적으로 수행한다.
    """
    values: dict[str, list[dict[str, Any]]] = {}
    failures: list[dict[str, Any]] = []
    for setting in settings:
        series_id = str(setting.get("series_id") or "<unknown>")
        if setting.get("collection_status") == "unsupported":
            failures.append({
                "series_id": series_id,
                "step": "actual",
                "status": "unsupported",
                "error": "source contract is unsupported",
                "type": "UnsupportedActualSourceError",
            })
            continue
        try:
            result = _one(setting, (starts_by_series or {}).get(series_id, start), end)
            # 응답을 받기 전의 배치 시작시각을 기록하면 발표 직전 PIT에 값이 새어 들어간다.
            collected_at = datetime.now(timezone.utc).isoformat()
            source, actual = _contract(setting)
            event_offset_days = _event_ref_period_offset(actual, series_id)
            values[series_id] = [
                {
                    "series_id": series_id,
                    "ref_period": (
                        _canonical_period(stamp.date(), str(setting["frequency"]))
                        + timedelta(days=event_offset_days)
                    ).isoformat(),
                    "value": float(value),
                    "unit": str(actual.get("unit") or "unknown"),
                    "provider": source,
                    "provider_code": actual.get("code") or actual.get("series"),
                    "effective_at": collected_at,
                    "collected_at": collected_at,
                    "time_precision": "collector_seen",
                    "availability_precision": "timestamp",
                    "provenance": {
                        "provider": source,
                        "provider_code": actual.get("code") or actual.get("series"),
                        "provider_ref_period": stamp.date().isoformat(),
                        "event_ref_period_offset_days": event_offset_days,
                        "effective_basis": "collector_seen_at",
                    },
                }
                for stamp, value in result.items()
            ]
            log.info("ECON actual OK %s (%d raw rows)", series_id, len(values[series_id]))
        except ActualNotAvailableYetError as exc:
            # 짧은 daily overlap에서 아직 새 관측이 없는 것은 장애가 아니다.
            # release-watch는 이 상태를 not_available_yet로 유지하고 다음 wake-up에
            # 재시도한다. HTTP/파싱/계약 오류는 아래 failed 경로로 남긴다.
            log.info("ECON actual pending %s: %s", series_id, exc)
            failures.append({
                "series_id": series_id,
                "step": "actual",
                "status": "not_available_yet",
                "error": str(exc),
                "type": type(exc).__name__,
            })
        except Exception as exc:  # noqa: BLE001 - source failure isolation.
            public = exc if isinstance(exc, ActualsError) else ActualProviderError(series_id, "unknown", exc)
            log.warning("ECON actual FAIL %s: %s", series_id, public)
            failures.append({
                "series_id": series_id,
                "step": "actual",
                "status": "failed",
                "error": str(public),
                "type": type(public).__name__,
            })
    return values, failures


def _canonical_period(stamp: date, frequency: str) -> date:
    """FRED 월초/ECOS 월말 차이를 family identity 하나로 정규화한다."""
    if frequency == "monthly":
        return date(stamp.year, stamp.month, 1)
    if frequency == "quarterly":
        return date(stamp.year, ((stamp.month - 1) // 3) * 3 + 1, 1)
    return stamp


def _event_ref_period_offset(actual: dict[str, Any], series_id: str) -> int:
    """provider observation date와 economic-release identity의 명시적 차이만 허용한다."""
    raw = actual.get("event_ref_period_offset_days", 0)
    try:
        offset = int(raw)
    except (TypeError, ValueError) as exc:
        raise ActualConfigurationError(f"{series_id}: invalid event_ref_period_offset_days") from exc
    if not -7 <= offset <= 7:
        raise ActualConfigurationError(f"{series_id}: event_ref_period_offset_days out of range")
    return offset
