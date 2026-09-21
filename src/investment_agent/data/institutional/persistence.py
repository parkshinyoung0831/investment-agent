"""institutional v1 저장소에 대한 ETL 보조 조회.

표 이름과 쓰기 규칙은 :mod:`repository`가 소유한다. 이 모듈은 13F
오케스트레이터가 필요로 하는 작은 조회·매핑 조합만 제공하며, 설정된
``Database`` 객체를 진입점에서 주입받는다.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from investment_agent.data.institutional.domain.holdings import Filing13F, effective_filings
from investment_agent.data.institutional.domain import managers as manager_config
from investment_agent.data.institutional.domain.models import FilingRecord
from investment_agent.data.institutional.repository import (
    SCHEMA,
    T_FILINGS,
    T_POSITIONS,
    InstitutionalRepository,
)
from investment_agent.data.institutional.infrastructure.sources.openfigi import MappingResult
from investment_agent.data.universe.repository import UniverseRepository
from investment_agent.platform.db.postgres import Database, sb

SCHEMA_INSTITUTIONAL = SCHEMA
SCHEMA_UNIVERSE = "universe"
T_SECURITIES = "securities"
T_IDENTIFIERS = "security_identifiers"

_CGS_TYPES = ("CUSIP", "CINS")
_database: Database | None = None


def configure(db: Database) -> None:
    """ETL 진입점이 v1 DB 객체를 주입한다."""
    global _database
    _database = db


def _db() -> Database:
    # ETL 진입점은 `configure()`로 자기 Database를 주입한다. 반면 trading evidence와
    # 알림은 진입점이 달라 주입 없이 같은 표를 읽는다 — 여기서 막으면 그쪽이
    # `RuntimeError`로 죽는다(`SupabaseRepository.guru_snapshot`이 실제로 그랬다).
    # universe·market persistence와 같은 fallback을 쓴다.
    return _database or Database(sb)


def _repository() -> InstitutionalRepository:
    return InstitutionalRepository(_db())


def get_active_manager_ciks() -> list[str]:
    return [str(row["manager_cik"]) for row in _repository().active_managers()]


def stored_accessions() -> set[str]:
    return _repository().known_accessions()


def delete_filings_before(cutoff_date: str) -> int:
    return _repository().delete_filings_before(date.fromisoformat(cutoff_date))


def ingest_filing(record: FilingRecord) -> int:
    """신고 원본과 모든 원천 행을 v1 표에 같은 순서로 기록한다."""
    repo = _repository()
    repo.upsert_filings([record.filing_payload()])
    positions = []
    for position in record.positions:
        row = position.as_dict()
        row["accession_no"] = record.accession_no
        row["identifier"] = row.pop("cusip")
        positions.append(row)
    return repo.upsert_positions(positions)


def get_identifier_cache() -> dict[tuple[str, str], dict[str, Any]]:
    """CUSIP/CINS 연결 캐시. 한 식별자에 행이 여럿이면 verified를 우선한다."""
    db = _db()
    rows = db.select_paged(
        lambda: db.table(SCHEMA_UNIVERSE, T_IDENTIFIERS).select(
            "identifier,identifier_type,security_id,mapping_status,source,updated_at"
        ).in_("identifier_type", list(_CGS_TYPES)),
        order_by="mapping_id",
    )
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["identifier"]), str(row["identifier_type"]))
        if key not in cache or row.get("mapping_status") == "verified":
            cache[key] = row
    return cache


def referenced_identifiers() -> set[tuple[str, str]]:
    db = _db()
    rows = db.select_paged(
        lambda: db.table(SCHEMA, T_POSITIONS).select("identifier,identifier_type"),
        order_by="accession_no,source_row_no",
    )
    return {
        (str(row["identifier"]), str(row["identifier_type"]))
        for row in rows
        if row.get("identifier") and row.get("identifier_type")
    }


def mapping_is_due(row: dict | None, *, now: datetime | None = None) -> bool:
    """다시 OpenFIGI에 물어볼 때인가. 확인된 연결은 다시 묻지 않고, 미확인·충돌은 30일마다."""
    if row is None:
        return True
    if str(row.get("mapping_status") or "") == "verified":
        return False
    point = now or datetime.now(timezone.utc)
    try:
        updated = datetime.fromisoformat(str(row["updated_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return updated.astimezone(timezone.utc) + timedelta(days=30) <= point


def known_universe_tickers() -> set[str]:
    db = _db()
    rows = db.select_paged(
        lambda: db.table(SCHEMA_UNIVERSE, T_SECURITIES).select("ticker")
        .eq("is_active_listing", True),
        order_by="ticker",
    )
    return {str(row["ticker"]).upper() for row in rows if row.get("ticker")}


def cache_mappings(mapping: Iterable[MappingResult], *, universe_tickers: set[str]) -> int:
    """OpenFIGI 결과를 식별자 연결로 적는다.

    OpenFIGI가 주는 ticker는 **지금** 표기다. 그 ticker를 상장 중이고 신원이 확인된
    종목이 들고 있을 때만 verified로 잇는다. 상장이 끝났거나 우리 목록에 없는 ticker는
    같은 표기를 다른 회사가 재사용했을 수 있어 unresolved로 두고 근거만 남긴다.
    """
    results = list(mapping)
    if not results:
        return 0
    universe = UniverseRepository(_db())
    securities = universe.securities_by_ticker([result.ticker for result in results if result.ticker])
    rows = []
    confirmed: dict[str, list[str]] = {}
    for result in results:
        ticker = str(result.ticker or "").upper()
        security = securities.get(ticker)
        evidence = ";".join(part for part in (
            f"openfigi:{result.source}",
            f"ticker={ticker}" if ticker else "",
            f"figi={result.figi}" if result.figi else "",
        ) if part)
        if (result.mapping_status == "mapped" and security is not None and ticker in universe_tickers
                and security.is_active_listing and security.is_identity_verified):
            status, security_id = "verified", security.security_id
            confirmed.setdefault(result.identifier_type, []).append(result.identifier)
        elif result.mapping_status == "ambiguous":
            status, security_id = "conflict", None
        else:
            status, security_id = "unresolved", None
        rows.append({
            "identifier_type": result.identifier_type,
            "identifier": result.identifier,
            "security_id": security_id,
            "mapping_status": status,
            "valid_from": None,
            "source": "openfigi",
            "evidence_ref": evidence,
        })
    written = universe.upsert_identifiers(rows)
    for identifier_type, identifiers in confirmed.items():
        _clear_unconfirmed(identifier_type, identifiers)
    return written


def _clear_unconfirmed(identifier_type: str, identifiers: list[str]) -> None:
    """확인된 연결이 생긴 식별자의 옛 미확인·충돌 행을 지운다(캐시가 둘로 갈라지지 않게)."""
    db = _db()
    for start in range(0, len(identifiers), 200):
        (db.table(SCHEMA_UNIVERSE, T_IDENTIFIERS).delete()
         .eq("identifier_type", identifier_type)
         .in_("identifier", identifiers[start:start + 200])
         .neq("mapping_status", "verified")
         .execute())


def _filing_row(filing: Filing13F, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "manager_cik": filing.manager_cik,
        "period_end": filing.period_end.isoformat(),
        "effective_accession_no": filing.accession_no,
        "effective_accepted_at": raw.get("accepted_at"),
        "effective_filing_date": filing.filing_date.isoformat(),
        "effective_form_type": filing.form_type,
        "effective_report_type": raw.get("report_type"),
        "effective_amendment_type": filing.amendment_type,
        "effective_amendment_no": filing.amendment_no,
        "effective_source_url": raw.get("source_url"),
        "effective_confidential_omitted": raw.get("confidential_omitted"),
    }


def effective_portfolio_state(
    as_of_at: datetime,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """v1 원천 표에서 accepted-at 이전의 현재·직전 포트폴리오를 만든다."""
    if as_of_at.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    db = _db()
    managers = {
        cik: row for cik, row in manager_config.MANAGER_CATALOG.items() if row.get("is_active")
    }
    cutoff = as_of_at.astimezone(timezone.utc).isoformat()
    filing_rows = db.select_paged(
        lambda: db.table(SCHEMA, T_FILINGS).select(
            "accession_no,manager_cik,period_end,form_type,report_type,filing_date,"
            "accepted_at,amendment_type,amendment_no,source_url,confidential_omitted"
        ).lte("accepted_at", cutoff),
        order_by="manager_cik,period_end,filing_date,accepted_at,accession_no",
    )
    by_period: dict[tuple[str, str], list[Filing13F]] = {}
    raw_by_accession: dict[str, dict[str, Any]] = {}
    for row in filing_rows:
        manager = str(row["manager_cik"])
        if manager not in managers:
            continue
        filing = Filing13F.from_row(row)
        by_period.setdefault((manager, filing.period_end.isoformat()), []).append(filing)
        raw_by_accession[filing.accession_no] = row

    current: dict[str, dict[str, Any]] = {}
    previous: dict[str, dict[str, Any]] = {}
    selected: set[str] = set()
    effective_key: dict[str, str] = {}
    for manager in managers:
        period_filings: dict[date, list[Filing13F]] = {}
        for (manager_cik, _period), filings in by_period.items():
            if manager_cik == manager:
                effective = effective_filings(filings)
                for filing in effective:
                    period_filings.setdefault(filing.period_end, []).append(filing)
        ordered = sorted(period_filings.items(), reverse=True)
        for index, (_period, filings) in enumerate(ordered[:2]):
            chosen = max(filings, key=lambda item: (item.filing_date, item.accession_no))
            event = _filing_row(chosen, raw_by_accession[chosen.accession_no])
            (current if index == 0 else previous)[manager] = event
            # 그 분기 포트폴리오를 이루는 신고(원본+덧붙임)는 모두 사건의 accession으로 묶는다.
            for item in filings:
                effective_key[item.accession_no] = chosen.accession_no
            selected.update(item.accession_no for item in filings)

    if not selected:
        return current, previous, []
    positions = db.select_in_chunks(
        schema=SCHEMA,
        table=T_POSITIONS,
        columns=("accession_no,source_row_no,issuer_name,identifier,identifier_type,"
                 "value_usd,quantity,quantity_type,position_kind"),
        filter_column="accession_no",
        values=sorted(selected),
        order_by="accession_no,source_row_no",
    )
    cache = get_identifier_cache()
    tickers = UniverseRepository(db).tickers_by_security_id(
        sorted({int(item["security_id"]) for item in cache.values()
                if item.get("security_id") is not None and item.get("mapping_status") == "verified"})
    )
    return current, previous, attach_tickers(
        [{"effective_accession_no": effective_key[row["accession_no"]], **row} for row in positions],
        cache, tickers,
    )


def attach_tickers(
    positions: list[dict[str, Any]],
    identifier_cache: dict[tuple[str, str], dict[str, Any]],
    tickers_by_security_id: dict[int, str],
) -> list[dict[str, Any]]:
    """보유 행에 `ticker`와 `mapping_status`를 붙인다.

    13F 원천에는 CUSIP만 있고 ticker가 없다. 소비자(evidence의 guru feature·후보 신호)는
    ticker로 묶으므로, 읽는 쪽이 요구하는 열을 여기서 채우지 않으면 guru 신호가 영구 결측이다.
    신원이 확인된(`verified`) 연결만 `mapped`로 인정하고, 나머지는 ticker 없이 상태만 남긴다.
    """
    out = []
    for row in positions:
        link = identifier_cache.get((str(row.get("identifier")), str(row.get("identifier_type"))))
        security_id = link.get("security_id") if link else None
        ticker = tickers_by_security_id.get(int(security_id)) if security_id is not None else None
        verified = bool(link) and link.get("mapping_status") == "verified" and ticker is not None
        out.append({
            **row,
            "ticker": ticker if verified else None,
            "mapping_status": "mapped" if verified else str((link or {}).get("mapping_status") or "unmapped"),
        })
    return out


__all__ = [
    "SCHEMA_INSTITUTIONAL", "SCHEMA_UNIVERSE", "T_IDENTIFIERS", "T_SECURITIES",
    "configure", "get_active_manager_ciks", "stored_accessions", "delete_filings_before",
    "ingest_filing", "get_identifier_cache", "referenced_identifiers", "mapping_is_due",
    "known_universe_tickers", "cache_mappings", "effective_portfolio_state", "attach_tickers",
]
