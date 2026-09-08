"""SEC 거래소 종목 마스터와 등록인 metadata를 수집한다."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from functools import partial
from typing import Any

from investment_agent.data.universe.infrastructure.sources.nasdaq_trader import fetch_security_metadata
from investment_agent.data.universe.domain.normalization import (
    classify_security_type,
    norm_ticker,
    sic_division,
)
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

_TICKERS_EXCHANGE_JSON = "https://www.sec.gov/files/company_tickers_exchange.json"
_US_LISTING_EXCHANGES = {"Nasdaq", "NYSE", "CBOE"}


def fetch_exchange_listed_tickers(
    *, get_json: Callable[[str], Any]
) -> list[dict]:
    """SEC 전체 거래소 master에서 거래 단위와 기본 entity 식별자를 만든다."""
    raw = get_json(_TICKERS_EXCHANGE_JSON)
    listing_metadata = fetch_security_metadata()
    fields = raw.get("fields") or []
    rows_by_ticker: dict[str, dict] = {}
    for values in raw.get("data") or []:
        row = dict(zip(fields, values))
        exchange = row.get("exchange")
        ticker = norm_ticker(row.get("ticker"))
        name = str(row.get("name") or "").strip()
        cik = row.get("cik")
        if exchange not in _US_LISTING_EXCHANGES or not ticker or not name or cik is None:
            continue
        metadata = listing_metadata.get(ticker) or {}
        security_title = metadata.get("security_title")
        sec_type = classify_security_type(
            security_title=security_title,
            ticker=ticker,
            is_etf=bool(metadata.get("is_etf")),
        )
        rows_by_ticker[ticker] = {
            "ticker": ticker,
            "cik": str(int(cik)).zfill(10),
            "company_name": name,
            "exchange_code": exchange,
            "security_type": sec_type,
            "security_title": security_title,
            "is_active_listing": True,
        }
    rows = [rows_by_ticker[ticker] for ticker in sorted(rows_by_ticker)]
    titled = sum(row["security_title"] is not None for row in rows)
    if titled / max(len(rows), 1) < 0.95:
        raise RuntimeError(
            f"listed-security title coverage is unsafe: {titled}/{len(rows)}"
        )
    log.info("  SEC exchange-listed tickers: %d (titles=%d)", len(rows), titled)
    return rows


_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ENTITY_WORKERS = 8


def _normalize_sic_code(value: Any) -> str | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return f"{number:04d}" if 0 <= number <= 9999 else None


def _fetch_entity_result(cik: str, *, get_json: Callable[[str], Any]) -> dict:
    """CIK 하나의 submissions metadata를 공통 SEC throttle 아래에서 조회한다."""
    url = _SUBMISSIONS_URL.format(cik=cik)
    try:
        data = get_json(url)
    except Exception as exc:  # noqa: BLE001 - exhausted provider errors enter the retry ledger
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        error_code = f"http_{status}" if status else type(exc).__name__
        log.warning("  entity FAIL CIK%s: %s", cik, error_code)
        return {
            "cik": cik,
            "outcome": "retryable_failure",
            "http_status": status,
            "error_code": error_code,
            "detail": {"stage": "submissions"},
        }

    entity_type = str(data.get("entityType") or "").strip() or None
    company_name = str(data.get("name") or "").strip() or None
    sic_code = _normalize_sic_code(data.get("sic"))
    sic_industry = str(data.get("sicDescription") or "").strip() or None
    division = sic_division(sic_code)
    if not sic_industry or not sic_code or sic_code == "0000":
        outcome = "source_not_classified"
    elif division is None:
        outcome = "mapping_failure"
    else:
        outcome = "success"
    return {
        "cik": cik,
        "outcome": outcome,
        "http_status": 200,
        "entity_type": entity_type,
        "company_name": company_name,
        "sic_code": sic_code,
        "sic_industry_name": sic_industry,
        "sic_division_name": division,
        "fiscal_year_end": str(data.get("fiscalYearEnd") or "").strip() or None,
        "state_of_incorporation": str(data.get("stateOfIncorporation") or "").strip() or None,
        "former_names": data.get("formerNames") if isinstance(data.get("formerNames"), list) else [],
        "detail": {},
    }


def fetch_entity_results(
    ciks: list[str], *, get_json: Callable[[str], Any]
) -> list[dict]:
    """고유 CIK별 SEC submissions metadata와 원천 상태를 반환한다.

    동일 CIK를 공유하는 ticker는 한 번만 조회한다. HTTP 실패와 SEC의 원천 미분류를
    분리하고, 요청 간격은 공통 SEC client가 보장한다.
    """
    normalized = sorted({str(cik).strip().zfill(10) for cik in ciks if cik})
    with ThreadPoolExecutor(max_workers=_ENTITY_WORKERS) as executor:
        results = list(executor.map(partial(_fetch_entity_result, get_json=get_json), normalized))
    counts: dict[str, int] = {}
    for result in results:
        outcome = result["outcome"]
        counts[outcome] = counts.get(outcome, 0) + 1
    log.info("  SEC entity CIK results: total=%d outcomes=%s", len(results), counts)
    return results
