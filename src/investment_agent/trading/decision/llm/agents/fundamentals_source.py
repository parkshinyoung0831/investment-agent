"""TradingAgents Fundamentals Analyst를 위한 SEC 재무제표·Gurus·거시지표 데이터 소스 어댑터."""
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


def fetch_fundamentals(ticker: str, curr_date: str, get_bundle: Callable[[], EvidenceBundle]) -> str:
    """재무제표, 밸류에이션, 세그먼트, 13F 기관 대가 지분을 시점 일치 번들에서 읽는다."""
    bundle = get_bundle()
    if not _symbol_ok(ticker, bundle) or not _date_ok(curr_date, bundle):
        return "NO_DATA_AVAILABLE: ticker/date is outside the active point-in-time bundle."
    return _domain_payload(bundle, "fundamentals", "estimates", "segments", "gurus")


def fetch_statement(
    ticker: str, freq: str = "quarterly", curr_date: str | None = None, *, get_bundle: Callable[[], EvidenceBundle]
) -> str:
    """손익계산서/대차대조표/현금흐름표를 시점 일치 번들에서 읽는다."""
    bundle = get_bundle()
    date_val = curr_date or parse_datetime(bundle.as_of_at).date().isoformat()
    return fetch_fundamentals(ticker, date_val, get_bundle=get_bundle)


def fetch_macro_indicators(
    indicator: str, curr_date: str, look_back_days: int | None = None, *, get_bundle: Callable[[], EvidenceBundle]
) -> str:
    """FRED/ECOS 거시경제 지표 및 경제 캘린더 발표 이력을 시점 일치 번들에서 읽는다."""
    bundle = get_bundle()
    if not _date_ok(curr_date, bundle):
        return "NO_DATA_AVAILABLE: requested macro date is after as_of_at."
    return _domain_payload(bundle, "macro", "economic_calendar")
