"""SEC·Nasdaq Trader·S&P 500 원천을 v1 universe 계약으로 적재한다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from collections.abc import Callable
from typing import Any

from investment_agent.data.universe.domain.models import Entity, MembershipSnapshot, Security
from investment_agent.data.universe.repository import INDEX_SP500, UniverseRepository
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class UniverseRefreshResult:
    entities: int
    securities: int
    identifiers: int
    memberships: int
    sec_failures: tuple[str, ...]


def _membership_hash(tickers: tuple[str, ...]) -> str:
    payload = json.dumps(list(tickers), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def refresh_universe(
    db: Database,
    *,
    sec_get_json: Callable[[str], Any],
    effective_date: date | None = None,
) -> UniverseRefreshResult:
    """현재 상장 master와 S&P 500 기준정보를 원천에서 다시 만든다.

    기존 DB를 읽어 보충하지 않는다. SEC 상세 metadata가 일시 실패한 경우에도 SEC
    exchange master가 준 CIK·회사명은 사실이므로 보존하되, 실패 CIK 목록을 결과에
    남겨 후속 수집이 성공으로 가장되지 않게 한다.
    """
    from investment_agent.data.universe.infrastructure.sources.sec_entities import (
        fetch_entity_results,
        fetch_exchange_listed_tickers,
    )
    from investment_agent.data.universe.infrastructure.sources.wikipedia_sp500 import fetch_current_members, fetch_selected_changes
    from investment_agent.data.universe.domain.normalization import build_membership_snapshots

    repo = UniverseRepository(db)
    listings = fetch_exchange_listed_tickers(get_json=sec_get_json)
    current_members = fetch_current_members()
    tracked = {str(value) for value in current_members["ticker"]}
    listing_by_cik = {str(row["cik"]): row for row in listings}

    detailed = fetch_entity_results(sorted(listing_by_cik), get_json=sec_get_json)
    failures = tuple(sorted(
        str(row.get("cik")) for row in detailed
        if row.get("outcome") == "retryable_failure"
    ))
    detailed_by_cik = {
        str(row["cik"]): row for row in detailed if row.get("outcome") != "retryable_failure"
    }
    entities: list[Entity] = []
    for cik, listing in sorted(listing_by_cik.items()):
        detail = detailed_by_cik.get(cik, {})
        entities.append(Entity(
            cik=cik,
            company_name=str(detail.get("company_name") or listing["company_name"]),
            sic_code=detail.get("sic_code"),
            sic_industry_name=detail.get("sic_industry_name"),
            sic_division_name=detail.get("sic_division_name"),
            fiscal_year_end=detail.get("fiscal_year_end"),
            entity_type=detail.get("entity_type"),
            state_of_incorporation=detail.get("state_of_incorporation"),
            former_names=tuple(detail.get("former_names") or ()),
        ))
    entities_written = repo.upsert_entities(entities)

    securities = [Security(
        security_id=0,
        ticker=str(row["ticker"]),
        cik=str(row["cik"]),
        exchange_code=row.get("exchange_code"),
        security_type=str(row.get("security_type") or "common_stock"),
        security_title=row.get("security_title"),
        is_active_listing=bool(row.get("is_active_listing", True)),
        is_tracked=str(row["ticker"]) in tracked,
    ) for row in listings]
    securities_written = repo.upsert_securities(securities)
    ids = repo.security_ids([security.ticker for security in securities])
    missing_ids = sorted({security.ticker for security in securities} - set(ids))
    if missing_ids:
        raise RuntimeError(f"universe upsert did not return security ids: {missing_ids[:10]}")
    identifiers_written = repo.upsert_identifiers({
        "identifier": security.ticker,
        "identifier_type": "TICKER",
        "security_id": ids[security.ticker],
        "mapping_status": "mapped",
        "source": "sec_exchange_master",
        "valid_from": "-infinity",
        "valid_to": None,
    } for security in securities)

    snapshots = build_membership_snapshots(current_members, fetch_selected_changes())
    today = effective_date or date.today()
    current = MembershipSnapshot(
        index_code=INDEX_SP500,
        effective_date=today,
        tickers=tuple(sorted(tracked)),
        source="wikipedia_current_components",
    )
    memberships_written = repo.record_membership(current, source_hash=_membership_hash(current.tickers))
    for row in snapshots:
        snapshot = MembershipSnapshot.from_row({
            "index_code": INDEX_SP500,
            "effective_date": row["effective_date"],
            "tickers": row["symbols"],
            "member_count": row["member_count"],
            "source": row["source"],
        })
        memberships_written += repo.record_membership(snapshot, source_hash=str(row["source_hash"]))
    log.info(
        "universe_refresh entities=%d securities=%d identifiers=%d memberships=%d sec_failures=%d",
        entities_written, securities_written, identifiers_written, memberships_written, len(failures),
    )
    return UniverseRefreshResult(
        entities_written, securities_written, identifiers_written, memberships_written, failures
    )


__all__ = ["UniverseRefreshResult", "refresh_universe"]
