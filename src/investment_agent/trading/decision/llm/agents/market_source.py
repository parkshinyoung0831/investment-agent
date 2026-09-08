"""TradingAgents Market Analyst를 위한 Supabase 시세·기술지표 데이터 소스 어댑터."""
from __future__ import annotations

from typing import Callable

from investment_agent.trading.contracts import EvidenceBundle, parse_datetime
from investment_agent.platform.serialization import canonical_json


def _symbol_ok(symbol: str, bundle: EvidenceBundle) -> bool:
    return str(symbol).upper() == bundle.ticker


def _date_ok(value: str | None, bundle: EvidenceBundle) -> bool:
    if not value:
        return True
    try:
        requested = str(value)[:10]
        return requested <= parse_datetime(bundle.as_of_at).date().isoformat()
    except (TypeError, ValueError):
        return False


def _domain_payload(bundle: EvidenceBundle, *domains: str) -> str:
    items = [item.to_dict() for item in bundle.evidence if item.domain in set(domains)]
    if not items:
        return "DATA_UNAVAILABLE: Supabase has no point-in-time evidence for this domain. Do not fabricate values."
    return canonical_json({
        "ticker": bundle.ticker,
        "as_of_at": bundle.as_of_at,
        "evidence": items,
        "missing_data": list(bundle.missing_data),
        "warnings": list(bundle.warnings),
    })


def fetch_stock_data(symbol: str, start_date: str, end_date: str, get_bundle: Callable[[], EvidenceBundle]) -> str:
    """과거 일별 OHLCV 시세 데이터를 시점 일치 번들에서 읽는다."""
    bundle = get_bundle()
    if not _symbol_ok(symbol, bundle) or not _date_ok(end_date, bundle):
        return "NO_DATA_AVAILABLE: ticker/date is outside the active point-in-time bundle."
    return _domain_payload(bundle, "market")


def fetch_indicator_data(
    symbol: str, indicator: str, curr_date: str, look_back_days: int = 30, *, get_bundle: Callable[[], EvidenceBundle]
) -> str:
    """RSI, MACD 등 기술적 지표 데이터를 시점 일치 번들에서 읽는다."""
    bundle = get_bundle()
    if not _symbol_ok(symbol, bundle) or not _date_ok(curr_date, bundle):
        return "NO_DATA_AVAILABLE: ticker/date is outside the active point-in-time bundle."
    return _domain_payload(bundle, "technical", "market")


def fetch_verified_market_snapshot(
    symbol: str, curr_date: str, look_back_days: int = 30, *, get_bundle: Callable[[], EvidenceBundle]
) -> str:
    """시장 검증 스냅샷 데이터를 시점 일치 번들에서 읽는다."""
    bundle = get_bundle()
    if not _symbol_ok(symbol, bundle) or not _date_ok(curr_date, bundle):
        return "NO_DATA_AVAILABLE: ticker/date is outside the active point-in-time bundle."
    return _domain_payload(bundle, "market", "technical")
