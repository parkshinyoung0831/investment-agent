"""v1 universe 저장·조회 계층.

이 모듈은 ETL 호출부가 필요한 작은 조합만 제공한다. 실제 표 이름과
identity 변환은 ``UniverseRepository``가 소유하고, 이 계층에는 v1 표/RPC가 아닌
구현을 남기지 않는다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json

from investment_agent.platform.db.postgres import sb
from investment_agent.platform.logging import get_logger
from investment_agent.data.universe.repository import (
    INDEX_SP500,
    SCHEMA,
    T_ENTITIES,
    T_MEMBERSHIPS,
    T_SECURITIES,
    UniverseRepository,
)
from investment_agent.platform.db.postgres import Database
from investment_agent.data.universe.domain.models import MembershipSnapshot, Security

log = get_logger(__name__)

SCHEMA_UNIVERSE = SCHEMA
_database: Database | None = None


def configure(db: Database | None) -> None:
    global _database
    _database = db


def _db() -> Database:
    # 알림·리포트처럼 별도 진입점 없이 호출되는 읽기 경로도 같은 v1 표를 보게 한다.
    return _database or Database(sb)


def _security_rows(*, tickers: list[str] | None = None, tracked_only: bool = False) -> list[dict]:
    repo = UniverseRepository(_db())
    if tickers is not None:
        wanted = sorted({str(value).upper() for value in tickers})
        if not wanted:
            return []
        securities = list(repo.securities_by_ticker(wanted).values())
        if tracked_only:
            securities = [security for security in securities if security.is_tracked]
    elif tracked_only:
        securities = repo.tracked_securities()
    else:
        securities = repo.all_securities()
    return [_security_to_row(security) for security in sorted(securities, key=lambda s: s.ticker)]


def _security_to_row(security: Security) -> dict:
    return {
        "security_id": security.security_id,
        "ticker": security.ticker,
        "cik": security.cik,
        "exchange_code": security.exchange_code,
        "security_type": security.security_type,
        "security_title": security.security_title,
        "is_active_listing": security.is_active_listing,
        "is_tracked": security.is_tracked,
    }


def select_tracked_tickers() -> list[str]:
    return [str(row["ticker"]) for row in _security_rows(tracked_only=True)]


def select_security_ids_by_ticker(tickers: list[str] | tuple[str, ...]) -> dict[str, int]:
    """Return the v1 security identity for each current ticker."""
    rows = _security_rows(tickers=[str(value).upper() for value in tickers])
    return {str(row["ticker"]).upper(): int(row["security_id"]) for row in rows}


def select_tickers_by_security_id(security_ids: list[int] | tuple[int, ...]) -> dict[int, str]:
    """Project v1 security identities back to the user-facing ticker."""
    return UniverseRepository(_db()).tickers_by_security_id(security_ids)


def select_tracked_ciks() -> list[str]:
    rows = _security_rows(tracked_only=True)
    return sorted({str(row["cik"]).zfill(10) for row in rows if row.get("cik")})


def select_security_profiles(
    tickers: list[str] | None = None, *, tracked_only: bool = False
) -> list[dict]:
    securities = _security_rows(tickers=tickers, tracked_only=tracked_only)
    ciks = sorted({str(row["cik"]) for row in securities if row.get("cik")})
    entities: list[dict] = []
    if ciks:
        entities = _db().select_in_chunks(
            schema=SCHEMA,
            table=T_ENTITIES,
            columns="cik,company_name,company_name_ko,sic_industry_name,sic_division_name",
            filter_column="cik",
            values=ciks,
            order_by="cik",
        )
    by_cik = {str(row["cik"]): row for row in entities}
    return [
        {
            "ticker": row["ticker"],
            "cik": str(row["cik"]).zfill(10) if row.get("cik") else None,
            "name": by_cik.get(str(row.get("cik")), {}).get("company_name") or row["ticker"],
            "name_ko": by_cik.get(str(row.get("cik")), {}).get("company_name_ko"),
            "sic_industry": by_cik.get(str(row.get("cik")), {}).get("sic_industry_name"),
            "sic_division": by_cik.get(str(row.get("cik")), {}).get("sic_division_name"),
        }
        for row in securities
    ]


def select_common_stock_tickers_by_cik(ciks: list[str] | None = None) -> dict[str, list[str]]:
    rows = [
        row for row in _security_rows()
        if row.get("security_type") == "common_stock" and row.get("is_active_listing")
    ]
    mapping: dict[str, list[str]] = {}
    for row in rows:
        if row.get("cik"):
            mapping.setdefault(str(row["cik"]).zfill(10), []).append(str(row["ticker"]))
    if ciks is None:
        return mapping
    wanted = {str(value).zfill(10) for value in ciks}
    return {key: value for key, value in mapping.items() if key in wanted}


def select_name_ko_pending(retry_before: str) -> list[str]:
    del retry_before  # v1은 실패 ledger가 아니라 entity 사실만 저장한다.
    rows = _security_rows(tracked_only=True)
    ciks = sorted({str(row["cik"]) for row in rows if row.get("cik")})
    if not ciks:
        return []
    entities = _db().select_in_chunks(
        schema=SCHEMA,
        table=T_ENTITIES,
        columns="cik,company_name_ko",
        filter_column="cik",
        values=ciks,
        order_by="cik",
    )
    missing = {str(row["cik"]) for row in entities if not row.get("company_name_ko")}
    representatives: dict[str, str] = {}
    for row in sorted(rows, key=lambda item: str(item["ticker"])):
        cik = str(row.get("cik") or "")
        if cik in missing:
            representatives.setdefault(cik, str(row["ticker"]))
    return list(representatives.values())


def select_entity_pending(*, tracked_only: bool = False, now: datetime | None = None) -> list[dict]:
    candidates = [row for row in _security_rows(tracked_only=tracked_only) if row.get("cik")]
    if not candidates:
        return []
    db = _db()
    entities = db.select_paged(
        lambda: db.table(SCHEMA, T_ENTITIES).select(
            "cik,entity_type,sic_code,sic_industry_name,sic_division_name,sec_metadata_updated_at"
        ),
        order_by="cik",
    )
    by_cik = {str(row["cik"]): row for row in entities}
    cutoff = now or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)

    def due(cik: str) -> bool:
        row = by_cik.get(cik)
        if row is None or not row.get("sec_metadata_updated_at"):
            return True
        refreshed = datetime.fromisoformat(str(row["sec_metadata_updated_at"]).replace("Z", "+00:00"))
        if refreshed.tzinfo is None:
            refreshed = refreshed.replace(tzinfo=timezone.utc)
        complete = all(row.get(field) for field in ("sic_code", "sic_industry_name", "sic_division_name"))
        return refreshed + timedelta(days=90 if complete else 180) <= cutoff

    return [row for row in candidates if due(str(row["cik"]))]


def upsert_securities(rows: list[dict]) -> int:
    if not rows:
        return 0
    db = _db()
    entities: dict[str, dict] = {}
    for row in rows:
        cik = str(row.get("cik") or "").zfill(10)
        if cik and cik not in entities:
            entities[cik] = {
                "cik": cik,
                "company_name": str(row.get("company_name") or cik),
                "former_names": [],
            }
    if entities:
        existing = db.select_in_chunks(
            schema=SCHEMA,
            table=T_ENTITIES,
            columns="cik",
            filter_column="cik",
            values=list(entities),
            order_by="cik",
        )
        existing_ciks = {str(row["cik"]) for row in existing}
        new_entities = [row for cik, row in entities.items() if cik not in existing_ciks]
        if new_entities:
            db.upsert(schema=SCHEMA, table=T_ENTITIES, rows=new_entities, on_conflict="cik")
    securities = [
        {
            "ticker": str(row["ticker"]),
            "cik": str(row["cik"]).zfill(10),
            "exchange_code": row.get("exchange_code"),
            "security_type": row.get("security_type") or "common_stock",
            "security_title": row.get("security_title"),
            "is_active_listing": bool(row.get("is_active_listing", True)),
        }
        for row in rows
    ]
    # `is_tracked`를 **일부러 싣지 않는다.** upsert는 payload에 있는 컬럼만 갱신하므로
    # 빼면 기존 값이 그대로 남고, 새 행은 선언의 기본값(false)을 받는다.
    #
    # 전에는 여기서 매번 false를 실어 7천여 종목의 게이트를 통째로 껐다. 거래소
    # master는 "무엇이 상장돼 있나"를 말할 뿐 "무엇을 수집하나"는 멤버십이 정한다.
    # 그 둘이 한 upsert에 섞여 있어서, S&P 변동이 없는 날 `universe_membership`이
    # 게이트를 끄고 조기 반환해 **모든 하류 수집이 0종목이 됐다** — 에러 없이.
    return db.upsert(schema=SCHEMA, table=T_SECURITIES, rows=securities, on_conflict="ticker")


def set_membership(rows: list[dict]) -> int:
    """멤버십 계산 결과를 securities에 반영한다.

    두 가지 의도를 받는다.

    * ``is_tracked``가 있는 행 — 수집 게이트를 그 값으로 정한다.
    * ``is_tracked``가 없는 행(과거 멤버) — **게이트를 건드리지 않는다.** 없으면
      상장 종료 상태로 ticker만 등록한다. 과거 멤버십 snapshot이 그 ticker를
      가리키므로 행이 없으면 `record_membership`이 통째로 거절한다.

    전에는 둘을 구분하지 않고 `is_tracked`가 없으면 True로 기본값을 줬다. 그래서
    지수에서 빠진 과거 멤버가 다시 tracked가 됐고(실측 129종목), 그만큼 모든
    하류 파이프라인이 영구히 더 돌았다. 없는 ticker는 UPDATE가 0행을 고쳐도
    성공으로 세어서, 과거 멤버 등록이 안 된 사실도 함께 가려졌다.
    """
    db = _db()
    wanted = []
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            wanted.append((ticker, row["is_tracked"] if "is_tracked" in row else None))
    if not wanted:
        return 0

    known = set(UniverseRepository(db).security_ids([ticker for ticker, _ in wanted]))
    changed = 0
    missing_rows = []
    for ticker, is_tracked in wanted:
        if ticker not in known:
            if is_tracked:
                # 현재 멤버인데 증권 마스터에 없다 — 발행사(CIK)를 모르면 재무를
                # 붙일 수 없으므로 조용히 만들지 않고 상류가 보게 둔다.
                log.warning("  현재 멤버인데 securities에 없음: %s", ticker)
                continue
            missing_rows.append({
                "ticker": ticker, "cik": None,
                "is_active_listing": False, "is_tracked": False,
            })
            continue
        if is_tracked is None:
            continue  # 이미 있는 과거 멤버 — 게이트는 그대로 둔다.
        db.table(SCHEMA, T_SECURITIES).update(
            {"is_tracked": bool(is_tracked)}
        ).eq("ticker", ticker).execute()
        changed += 1
    if missing_rows:
        db.table(SCHEMA, T_SECURITIES).insert(missing_rows).execute()
        changed += len(missing_rows)
    return changed


def select_latest_sp500_symbols() -> set[str]:
    snapshot = UniverseRepository(_db()).latest_membership(index_code=INDEX_SP500)
    return set(snapshot.tickers) if snapshot else set()


def append_memberships(rows: list[dict]) -> int:
    if not rows:
        raise ValueError("historical membership snapshots must not be empty")
    repository = UniverseRepository(_db())
    written = 0
    for row in sorted(rows, key=lambda item: str(item["effective_date"])):
        raw_tickers = [str(value).upper() for value in row.get("symbols") or []]
        tickers = tuple(sorted(set(raw_tickers)))
        snapshot = MembershipSnapshot.from_row({
            "index_code": INDEX_SP500,
            "effective_date": str(row["effective_date"]),
            "tickers": list(tickers),
            "member_count": row.get("member_count", len(raw_tickers)),
            "source": str(row.get("source") or "universe_membership"),
        })
        written += repository.record_membership(snapshot, source_hash=str(row["source_hash"]))
    return written


def apply_toss_names(names: dict[str, str], attempted: list[str]) -> None:
    if not attempted or not names:
        return
    securities = _security_rows(tickers=attempted)
    by_ticker = {str(row["ticker"]): str(row["cik"]) for row in securities if row.get("cik")}
    rows = [
        {"cik": by_ticker[ticker], "company_name_ko": str(names[ticker])}
        for ticker in attempted
        if ticker in names and ticker in by_ticker
    ]
    for row in rows:
        _db().table(SCHEMA, T_ENTITIES).update(
            {"company_name_ko": row["company_name_ko"]}
        ).eq("cik", row["cik"]).execute()


def apply_entity_results(results: list[dict]) -> int:
    if not results:
        return 0
    db = _db()
    ciks = sorted({str(row.get("cik") or "").zfill(10) for row in results if row.get("cik")})
    existing = db.select_in_chunks(
        schema=SCHEMA,
        table=T_ENTITIES,
        columns="cik,company_name,company_name_ko,former_names",
        filter_column="cik",
        values=ciks,
        order_by="cik",
    ) if ciks else []
    by_cik = {str(row["cik"]): row for row in existing}
    now = datetime.now(timezone.utc).isoformat()
    payload = []
    for result in results:
        cik = str(result.get("cik") or "").zfill(10)
        current = by_cik.get(cik, {})
        company_name = str(result.get("company_name") or current.get("company_name") or "").strip()
        if not company_name:
            continue
        payload.append({
            "cik": cik,
            "company_name": company_name,
            "company_name_ko": current.get("company_name_ko"),
            "entity_type": result.get("entity_type"),
            "sic_code": result.get("sic_code"),
            "sic_industry_name": result.get("sic_industry_name"),
            "sic_division_name": result.get("sic_division_name"),
            "fiscal_year_end": result.get("fiscal_year_end"),
            "state_of_incorporation": result.get("state_of_incorporation"),
            "former_names": result.get("former_names") or current.get("former_names") or [],
            "sec_metadata_updated_at": now,
        })
    return db.upsert(schema=SCHEMA, table=T_ENTITIES, rows=payload, on_conflict="cik")


def select_sp500_membership_snapshots(*, start_date: date, end_date: date) -> list[dict]:
    if end_date < start_date:
        raise ValueError("historical membership end_date must not precede start_date")
    db = _db()
    rows = db.select_paged(
        lambda: db.table(SCHEMA, T_MEMBERSHIPS).select(
            "security_id,valid_from,valid_to,source,source_hash,securities(ticker)"
        ).eq("index_code", INDEX_SP500).lte("valid_from", end_date.isoformat()),
        order_by="valid_from,security_id",
    )
    boundaries = {start_date.isoformat()}
    boundaries.update(str(value) for row in rows for value in (row["valid_from"], row.get("valid_to"))
                      if value and start_date.isoformat() < str(value) <= end_date.isoformat())
    result = []
    for boundary in sorted(boundaries):
        active = [row for row in rows if str(row["valid_from"]) <= boundary and (not row.get("valid_to") or boundary < str(row["valid_to"]))]
        ids = sorted(int(row["security_id"]) for row in active)
        tickers = sorted({str((row.get(T_SECURITIES) or {}).get("ticker") or "").upper() for row in active})
        if "" in tickers or len(ids) != len(set(ids)) or len(tickers) != len(ids) or not 450 <= len(ids) <= 520:
            raise RuntimeError("point-in-time S&P 500 membership is unavailable or inconsistent")
        digest = hashlib.sha256(json.dumps({"date": boundary, "security_ids": ids}, sort_keys=True).encode()).hexdigest()
        result.append({
            "effective_date": boundary,
            "symbols": tickers,
            "security_ids": ids,
            "member_count": len(tickers),
            "source": "universe.index_memberships",
            "source_hash": digest,
        })
    return result


__all__ = [
    "SCHEMA_UNIVERSE", "T_ENTITIES", "T_SECURITIES",
    "configure", "select_tracked_tickers",
    "select_tracked_ciks", "select_security_profiles", "select_common_stock_tickers_by_cik",
    "select_name_ko_pending", "select_entity_pending", "upsert_securities", "set_membership",
    "select_latest_sp500_symbols", "append_memberships", "apply_toss_names",
    "apply_entity_results", "select_sp500_membership_snapshots",
]
