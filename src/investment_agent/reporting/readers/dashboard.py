"""Dashboard가 사용하는 reporting read model의 얇은 reader.

Dashboard는 이 모듈을 통해서만 reporting view를 읽는다. 화면 계층에 Supabase
client·schema 이름·pagination 정책을 다시 들여오지 않는다.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
import re
from typing import Any
from collections.abc import Sequence

import pandas as pd

from investment_agent.platform.cache import cache_data
from investment_agent.platform.db.postgres import service_client
from investment_agent.reporting.models import DataResult, public_exception_message
from investment_agent.reporting.readers.financial import ReportingQueries

SOURCE = "DB 저장 데이터 · v1 Supabase"
MACRO_LOOKBACK_DAYS = 400
_PRICE_PERIOD_DAYS = {"1mo": 31, "3mo": 93, "6mo": 186, "1y": 366, "2y": 731, "5y": 1826, "10y": 3653, "max": None}


def _blocked() -> DataResult | None:
    if os.environ.get("DASHBOARD_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return DataResult.offline(source=SOURCE)
    if not (os.environ.get("SUPABASE_URL", "").strip() and os.environ.get("SUPABASE_SERVICE_KEY", "").strip()):
        return DataResult.unconfigured(source=SOURCE)
    return None


def _read(view: str, **kwargs: object) -> DataResult:
    blocked = _blocked()
    if blocked:
        return blocked
    try:
        return ReportingQueries.from_client(service_client()).read(view, **kwargs)
    except Exception as error:
        return DataResult.error(source=f"{SOURCE} · reporting.{view}", message=public_exception_message("Reporting 조회에 실패했습니다.", error))


@cache_data(ttl="5m", max_entries=4)
def load_macro_window(scope: str = "all") -> DataResult:
    if scope not in {"core", "watch", "all"}:
        return DataResult.blocked(source=SOURCE, message="지원하지 않는 매크로 범위입니다.")
    from investment_agent.reporting.services.macro.constants import CORE_SERIES, WATCH_SERIES
    ids = set(CORE_SERIES) if scope == "core" else set(WATCH_SERIES) if scope == "watch" else set(CORE_SERIES) | set(WATCH_SERIES)
    today = datetime.now(timezone.utc).date()
    return _read("macro_observations", in_values={"series_id": tuple(sorted(ids))}, start=today - timedelta(days=MACRO_LOOKBACK_DAYS), end=today)


@cache_data(ttl="5m", max_entries=4)
def load_econ_upcoming(days: int = 30) -> DataResult:
    now = datetime.now(timezone.utc)
    result = _read("macro_release_summary", start=now, end=now + timedelta(days=max(1, min(int(days), 365))))
    if result.status not in {"ok", "empty"}:
        return result
    rows = [row for row in result.rows if row.get("status") in {"scheduled", "not_available_yet"}]
    return DataResult.empty(source=result.source, message="향후 경제발표 일정이 없습니다.") if not rows else DataResult.ok(rows=rows, source=result.source)


def _window(start: datetime, end: datetime) -> DataResult:
    return _read("macro_release_summary", start=start, end=end)


@cache_data(ttl="5m", max_entries=4)
def load_econ_recent_results(days: int = 45) -> DataResult:
    now = datetime.now(timezone.utc)
    result = _window(now - timedelta(days=max(1, min(int(days), 365))), now)
    if result.status not in {"ok", "empty"}:
        return result
    rows = sorted((row for row in result.rows if row.get("status") == "released"), key=lambda row: str(row.get("scheduled_at") or row.get("first_actual_at") or ""), reverse=True)
    return DataResult.empty(source=result.source, message="최근 경제발표 결과가 없습니다.") if not rows else DataResult.ok(rows=rows, source=result.source)


@cache_data(ttl="5m", max_entries=16)
def load_econ_calendar_window(start_at: str, end_at: str) -> DataResult:
    try:
        result = _window(datetime.fromisoformat(start_at), datetime.fromisoformat(end_at))
        return result if result.status != "empty" else DataResult.empty(source=result.source, message="선택한 기간에 경제발표가 없습니다.")
    except ValueError:
        return DataResult.blocked(source=SOURCE, message="유효한 ISO 기간이 필요합니다.")


@cache_data(ttl="10m", max_entries=2)
def load_econ_series() -> DataResult:
    from investment_agent.reporting.services.economic_releases import enriched_series
    # macro.series에는 발표 지표와 시장 관측 지표가 함께 산다(30 + 32). 이 화면은
    # 발표만 다루고, 코드의 발표 카탈로그도 그 30개만 안다 — 걸러내지 않으면
    # 시장 지표 첫 행에서 "unknown ECON series"로 화면 전체가 죽는다.
    series = _read("macro_series", equals={"domain": "economic_release"})
    measures = _read("macro_measures")
    if series.status not in {"ok", "empty"}:
        return series
    if measures.status not in {"ok", "empty"}:
        return measures
    payload: dict[str, Any] = {"series": enriched_series(series.rows), "measures": measures.rows}
    return DataResult.empty(value=payload, source=f"{SOURCE} · reporting.macro_series", message="등록된 경제지표 마스터가 없습니다.") if not series.rows else DataResult.ok(value=payload, source=f"{SOURCE} · reporting.macro_series")


@cache_data(ttl="10m", max_entries=32)
def load_econ_series_history(series_id: str, limit: int = 120) -> DataResult:
    series_id = str(series_id).strip()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", series_id):
        return DataResult.blocked(source=SOURCE, message="유효한 ECON series_id가 필요합니다.")
    result = _read("macro_release_summary", equals={"series_id": series_id})
    if result.status not in {"ok", "empty"}:
        return result
    rows = sorted(result.rows, key=lambda row: str(row.get("ref_period") or ""), reverse=True)[:max(1, min(int(limit), 500))]
    return DataResult.empty(source=result.source, message="이 series의 저장된 발표 이력이 없습니다.") if not rows else DataResult.ok(rows=rows, source=result.source)


@cache_data(ttl="10m", max_entries=32)
def load_econ_detail(event_key: str) -> DataResult:
    from investment_agent.reporting.services.economic_releases import parse_event_key
    parsed = parse_event_key(event_key)
    if parsed is None:
        return DataResult.blocked(source=SOURCE, message="발표 키는 SERIES_ID:YYYY-MM-DD 형식이어야 합니다.")
    series_id, ref_period = parsed
    forecasts = _read("macro_release_forecasts", equals={"series_id": series_id, "ref_period": ref_period})
    actuals = _read("macro_release_actuals", equals={"series_id": series_id, "ref_period": ref_period})
    if forecasts.status not in {"ok", "empty"}:
        return forecasts
    if actuals.status not in {"ok", "empty"}:
        return actuals
    payload = {"forecasts": forecasts.rows, "actuals": actuals.rows}
    return DataResult.empty(value=payload, source=f"{SOURCE} · reporting.macro_release", message="선택한 발표의 저장 데이터가 없습니다.") if not any(payload.values()) else DataResult.ok(value=payload, source=f"{SOURCE} · reporting.macro_release")


@cache_data(ttl="2m", max_entries=32)
def load_price_history(tickers: str | Sequence[str], period: str = "6mo") -> DataResult:
    values = (tickers,) if isinstance(tickers, str) else tuple(tickers)
    symbols = tuple(dict.fromkeys(str(value or "").strip().upper() for value in values if str(value or "").strip()))
    source = f"{SOURCE} · reporting.prices_daily"
    if not symbols or len(symbols) > 40 or any(not re.fullmatch(r"[A-Z0-9][A-Z0-9.^-]{0,14}", symbol) for symbol in symbols):
        return DataResult.blocked(source=source, message="유효한 종목 코드가 필요합니다.")
    days = _PRICE_PERIOD_DAYS.get(str(period or "").strip().lower())
    if str(period or "").strip().lower() not in _PRICE_PERIOD_DAYS:
        return DataResult.blocked(source=source, message="허용되지 않은 가격 조회 기간입니다.")
    end = datetime.now(timezone.utc).date()
    result = _read("prices_daily", in_values={"ticker": symbols}, start=end - timedelta(days=days) if days else end - timedelta(days=36530), end=end)
    if result.status not in {"ok", "empty"}:
        return result
    frame = pd.DataFrame(result.rows)
    if frame.empty:
        return DataResult.empty(source=source, value=frame, message="저장된 가격 관측값이 없습니다.")
    frame["Date"] = pd.to_datetime(frame["trade_date"], utc=True, errors="coerce").dt.tz_localize(None)
    frame = frame.dropna(subset=["Date", "close"]).sort_values(["Date", "ticker"])
    fields = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    if len(symbols) == 1:
        value = frame.set_index("Date")[list(fields)].rename(columns=fields)
    else:
        value = frame.pivot_table(index="Date", columns="ticker", values=list(fields), aggfunc="last")
        value = value.reindex(columns=pd.MultiIndex.from_product([list(fields), list(symbols)]))
        value.columns = pd.MultiIndex.from_tuples([(fields[str(field)], str(ticker).upper()) for field, ticker in value.columns], names=["Price", "Ticker"])
    value.index.name = "Date"
    missing = sorted(set(symbols) - {str(row.get("ticker")).upper() for row in result.rows})
    return DataResult.ok(value=value, source=source, message=f"가격 누락 종목: {', '.join(missing)}" if missing else None)


@cache_data(ttl="15m", max_entries=2)
def load_strategy_data() -> DataResult:
    """Research가 소유한 전략·배분 read model을 Dashboard에 투영한다."""
    from investment_agent.reporting.readers.research import load_local_strategy_data
    try:
        payload = load_local_strategy_data()
        if not payload.get("strategies") and not payload.get("allocations"):
            return DataResult.empty(value=payload, source="Research 로컬 · DuckDB strategy allocations", message="저장된 전략 또는 배분 이력이 없습니다.")
        return DataResult.ok(value=payload, source="Research 로컬 · DuckDB strategy allocations")
    except Exception as error:
        return DataResult.error(source="Research 로컬 · DuckDB strategy allocations", message=public_exception_message("전략 DB 조회에 실패했습니다.", error))


def guru_managers() -> list[dict[str, Any]]:
    """추적 대상 manager 사실 + 화면 해석을 reporting 경계로 노출한다.

    manager_cik/name/fund_name/is_active의 SSOT는 코드 설정이다 — Dashboard는
    domain 구현을 직접 가져오지 않으므로 이 함수를 거쳐 읽는다.
    """
    from investment_agent.data.institutional.domain.managers import active_managers

    return active_managers()


@cache_data(ttl="30m", max_entries=2)
def load_guru_data() -> DataResult:
    """13F 화면 payload. manager 사실은 코드 설정, filings/positions는 reporting view가 소유한다."""
    manager_rows = guru_managers()
    manager_ciks = tuple(str(row["manager_cik"]) for row in manager_rows)
    filings = _read("institutional_filings", in_values={"manager_cik": manager_ciks}) if manager_ciks else DataResult.empty(source="reporting.institutional_filings")
    if filings.status not in {"ok", "empty"}:
        return filings
    accessions = tuple(str(row["accession_no"]) for row in filings.rows)
    positions = _read("institutional_positions", in_values={"accession_no": accessions}) if accessions else DataResult.empty(source="reporting.institutional_positions")
    if positions.status not in {"ok", "empty"}:
        return positions
    cusip_map = [{"cusip": row.get("cusip"), "ticker": row.get("ticker"), "updated_at": None} for row in positions.rows if row.get("cusip")]
    payload = {"managers": manager_rows, "filings": filings.rows, "positions": positions.rows, "cusip_map": cusip_map, "smart_changes": []}
    return DataResult.empty(value=payload, source="reporting institutional", message="활성 13F 매니저 또는 공시 데이터가 없습니다.") if not manager_rows and not filings.rows else DataResult.ok(value=payload, source="reporting institutional")


@cache_data(ttl="30m", max_entries=2)
def load_tickers() -> DataResult:
    """AI 화면의 종목 선택 목록은 reporting.securities만 읽는다."""
    result = _read("securities", equals={"is_tracked": True})
    if result.status not in {"ok", "empty"}:
        return result
    # 추적(S&P 500)과 관심(watchlist)은 다른 사실이다. 전에는 뷰가 관심 컬럼을
    # 내보내지 않아 tracked를 관심으로 베껴 썼고, 그래서 화면이 추적 종목 전부를
    # 관심 기업으로 표시했다.
    rows = [
        {
            **row,
            "watchlist_active": bool(row.get("is_watchlisted")),
            "watchlist_names": list(row.get("watchlist_sources") or []),
            "fundamentals_watchlist": bool(row.get("is_watchlisted")),
            "watchlist": list(row.get("watchlist_sources") or []),
        }
        for row in result.rows
    ]
    return DataResult.empty(source=result.source, message="추적 종목이 없습니다.") if not rows else DataResult.ok(rows=rows, source=result.source)


@cache_data(ttl="2m", max_entries=2)
def load_execution_data() -> DataResult:
    """Execution 관측 원장은 reporting view로만 Dashboard에 공개한다."""
    payload: dict[str, list[dict[str, Any]]] = {key: [] for key in ("control_state", "intents", "approvals", "orders", "order_events", "fills", "tca_reports", "reconciliations")}
    for key, view in (("control_state", "execution_control_state"), ("intents", "execution_intents"), ("approvals", "execution_approvals"), ("orders", "execution_orders"), ("fills", "execution_fills")):
        result = _read(view)
        if result.status not in {"ok", "empty"}:
            return result
        payload[key] = result.rows
    return DataResult.empty(value=payload, source="reporting execution", message="아직 저장된 실행·체결 기록이 없습니다.") if not any(payload.values()) else DataResult.ok(value=payload, source="reporting execution")


__all__ = [
    "load_econ_calendar_window", "load_econ_detail", "load_econ_recent_results",
    "load_econ_series", "load_econ_series_history", "load_econ_upcoming",
    "load_execution_data", "load_guru_data", "load_macro_window", "load_price_history", "load_strategy_data", "load_tickers",
]
