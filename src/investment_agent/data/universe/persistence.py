"""v1 universe 저장·조회 계층.

이 모듈은 ETL 호출부가 필요한 작은 조합만 제공한다. 실제 표 이름과
identity 변환은 ``UniverseRepository``가 소유하고, 이 계층에는 v1 표/RPC가 아닌
구현을 남기지 않는다.

## 신원 판정은 동기화가 하고, 확실하지 않으면 멈춘다

SEC 거래소 목록은 "지금 무엇이 상장돼 있나"만 말한다. 그것을 ticker로 upsert하면
티커 재사용 때 옛 종목을 새 회사로 덮어쓰고, 개명 때 같은 종목이 두 ID로 갈라진다.
그래서 `upsert_securities`는 기존 종목과 대조해 네 가지로 가른다.

* 같은 ticker·같은 CIK — 같은 종목. 표기 metadata만 갱신한다.
* 같은 ticker·다른 CIK — 신원 충돌. 건드리지 않고 경고로 남긴다.
* 새 ticker이고 그 CIK의 상장 종목 중 목록에서 사라진 것이 정확히 하나 — 개명.
  같은 ID의 ticker를 바꾸고 TICKER 이력을 닫고 연다(FB→META).
* 그 밖의 새 ticker — 새 종목.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from collections import defaultdict
from zoneinfo import ZoneInfo

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
        "is_identity_verified": security.is_identity_verified,
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


def _us_market_today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _listing_payload(row: dict, *, security_id: int | None = None) -> dict:
    payload = {
        "ticker": str(row["ticker"]),
        "cik": str(row["cik"]).zfill(10),
        "exchange_code": row.get("exchange_code"),
        "security_type": row.get("security_type") or "common_stock",
        "security_title": row.get("security_title"),
        "is_active_listing": True,
        "is_identity_verified": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if security_id is not None:
        payload = {"security_id": security_id, **payload}
    return payload


def upsert_securities(rows: list[dict]) -> int:
    """SEC 거래소 목록을 기존 종목과 대조해 반영한다. 반영한 종목 수를 돌려준다.

    `is_tracked`는 **싣지 않는다.** 거래소 목록은 "무엇이 상장돼 있나"를 말할 뿐
    "무엇을 수집하나"는 멤버십이 정한다. 한 upsert에 섞였을 때 게이트가 통째로 꺼져
    모든 하류 수집이 에러 없이 0종목이 된 적이 있다.
    """
    if not rows:
        return 0
    db = _db()
    repository = UniverseRepository(db)
    entities: dict[str, dict] = {}
    for row in rows:
        cik = str(row.get("cik") or "").zfill(10)
        if cik and cik not in entities:
            entities[cik] = {"cik": cik, "company_name": str(row.get("company_name") or cik), "former_names": []}
    if entities:
        existing = db.select_in_chunks(
            schema=SCHEMA, table=T_ENTITIES, columns="cik", filter_column="cik",
            values=list(entities), order_by="cik",
        )
        existing_ciks = {str(row["cik"]) for row in existing}
        new_entities = [row for cik, row in entities.items() if cik not in existing_ciks]
        if new_entities:
            db.upsert(schema=SCHEMA, table=T_ENTITIES, rows=new_entities, on_conflict="cik")

    listed = {str(row["ticker"]): row for row in rows}
    securities = repository.all_securities()
    active_by_ticker = {s.ticker: s for s in securities if s.is_active_listing}
    active_by_cik: dict[str, list] = defaultdict(list)
    for security in active_by_ticker.values():
        if security.cik:
            active_by_cik[security.cik].append(security)
    new_by_cik: dict[str, list[dict]] = defaultdict(list)
    for ticker, row in listed.items():
        if ticker not in active_by_ticker:
            new_by_cik[str(row["cik"]).zfill(10)].append(row)

    updates: list[dict] = []
    inserts: list[dict] = []
    renames: list[tuple[object, dict]] = []
    conflicts: list[str] = []
    for ticker, row in sorted(listed.items()):
        cik = str(row["cik"]).zfill(10)
        current = active_by_ticker.get(ticker)
        if current is not None:
            if current.cik and current.cik != cik:
                conflicts.append(f"{ticker}: listed cik={cik} stored cik={current.cik} id={current.security_id}")
                continue
            updates.append(_listing_payload(row, security_id=current.security_id))
            continue
        vanished = [s for s in active_by_cik.get(cik, []) if s.ticker not in listed]
        if len(vanished) == 1 and len(new_by_cik[cik]) == 1 and vanished[0].security_type == (
            row.get("security_type") or "common_stock"
        ):
            renames.append((vanished[0], row))
            updates.append(_listing_payload(row, security_id=vanished[0].security_id))
            continue
        inserts.append(_listing_payload(row))

    for conflict in conflicts:
        log.warning("  identity conflict held (not merged): %s", conflict)
    if updates:
        db.upsert(schema=SCHEMA, table=T_SECURITIES, rows=updates, on_conflict="security_id")
    if inserts:
        for start in range(0, len(inserts), 500):
            db.table(SCHEMA, T_SECURITIES).insert(inserts[start:start + 500]).execute()
    _sync_ticker_history(repository, listed, renames)
    log.info(
        "  listing sync: updated=%d renamed=%d inserted=%d conflicts=%d",
        len(updates) - len(renames), len(renames), len(inserts), len(conflicts),
    )
    return len(updates) + len(inserts)


def _sync_ticker_history(repository: UniverseRepository, listed: dict[str, dict], renames: list) -> None:
    """상장 중인 종목마다 지금 유효한 TICKER 연결이 하나 있게 한다.

    시작일은 우리가 그 표기를 처음 확인한 날이다. 실제 거래 시작일이 아니라 "적어도
    이날부터 이 표기였다"는 보수적 사실이다. 개명은 옛 연결을 오늘로 닫고 새로 연다.
    """
    today = _us_market_today()
    current = {str(row["identifier"]): row for row in repository.current_identifiers("TICKER")
               if row.get("mapping_status") == "verified"}
    for old, _row in renames:
        previous = current.get(old.ticker)
        if previous is not None and int(previous["security_id"]) == old.security_id:
            repository.close_identifier(int(previous["mapping_id"]), valid_to=today)
            current.pop(old.ticker, None)
    ids = repository.security_ids(list(listed))
    missing = []
    for ticker, security_id in sorted(ids.items()):
        row = current.get(ticker)
        if row is not None and int(row["security_id"]) == security_id:
            continue
        if row is not None:
            # 같은 표기를 다른 종목이 들고 있다 — 충돌 경로가 이미 경고했으므로 여기서 덮지 않는다.
            continue
        missing.append({
            "identifier_type": "TICKER", "identifier": ticker, "security_id": security_id,
            "mapping_status": "verified", "valid_from": today.isoformat(), "source": "sec_listing",
        })
    if missing:
        repository.upsert_identifiers(missing)


def set_membership(rows: list[dict]) -> int:
    """멤버십 계산 결과를 securities에 반영한다.

    두 가지 의도를 받는다.

    * ``is_tracked``가 있는 행 — 수집 게이트를 그 값으로 정한다.
    * ``is_tracked``가 없는 행(과거 멤버) — **게이트를 건드리지 않는다.** 없으면
      신원 미확인 자리표시 종목으로 ticker만 등록한다. 과거 멤버십 snapshot이 그
      ticker를 가리키므로 행이 없으면 `record_membership`이 통째로 거절한다.

    게이트는 신원이 확인된 종목에만 켠다. ticker만 같은 자리표시 종목에 켜면 다른 회사의
    자료를 수집한다.
    """
    db = _db()
    wanted = []
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            wanted.append((ticker, row["is_tracked"] if "is_tracked" in row else None))
    if not wanted:
        return 0

    known = UniverseRepository(db).securities_by_ticker([ticker for ticker, _ in wanted])
    changed = 0
    missing_rows = []
    for ticker, is_tracked in wanted:
        security = known.get(ticker)
        if security is None:
            if is_tracked:
                log.warning("  현재 멤버인데 securities에 없음: %s", ticker)
                continue
            missing_rows.append(_placeholder(ticker))
            continue
        if is_tracked is None:
            continue  # 이미 있는 과거 멤버 — 게이트는 그대로 둔다.
        if is_tracked and not (security.is_active_listing and security.is_identity_verified):
            log.warning("  현재 멤버인데 상장·신원 확인된 종목이 없음: %s", ticker)
            continue
        db.table(SCHEMA, T_SECURITIES).update(
            {"is_tracked": bool(is_tracked)}
        ).eq("security_id", security.security_id).execute()
        changed += 1
    if missing_rows:
        db.table(SCHEMA, T_SECURITIES).insert(missing_rows).execute()
        changed += len(missing_rows)
    return changed


def _placeholder(ticker: str) -> dict:
    """과거 지수 기록에서만 이름이 나온 종목. 발행사를 모르고 수집 대상이 될 수 없다."""
    return {
        "ticker": ticker, "cik": None, "is_active_listing": False,
        "is_identity_verified": False, "is_tracked": False,
    }


def select_latest_sp500_symbols() -> set[str]:
    snapshot = UniverseRepository(_db()).latest_membership(index_code=INDEX_SP500)
    return set(snapshot.tickers) if snapshot else set()


def append_memberships(rows: list[dict]) -> int:
    """과거 멤버십 스냅샷을 시간순으로 반영한다.

    과거 스냅샷의 ticker는 그때의 표기다. 지금 같은 ticker가 같은 회사라고 믿을 수 있는
    것은 **가장 최근 스냅샷부터 그 스냅샷까지 끊김 없이 지수에 있었던 경우**뿐이다.
    중간에 빠졌다가 다시 나타난 ticker는 다른 회사가 표기를 재사용했을 수 있으므로
    신원 미확인 자리표시 종목에 붙인다 — 다른 회사의 과거를 지금 종목에 섞지 않는다.
    """
    if not rows:
        raise ValueError("historical membership snapshots must not be empty")
    repository = UniverseRepository(_db())
    ordered = sorted(rows, key=lambda item: str(item["effective_date"]))
    ticker_sets = [
        tuple(sorted({str(value).upper() for value in row.get("symbols") or []}))
        for row in ordered
    ]
    continuous: list[set[str]] = [set()] * len(ordered)
    running: set[str] | None = None
    for index in range(len(ordered) - 1, -1, -1):
        members = set(ticker_sets[index])
        running = members if running is None else running & members
        continuous[index] = set(running)

    everything = sorted({ticker for tickers in ticker_sets for ticker in tickers})
    current = repository.securities_by_ticker(everything)

    def is_current(ticker: str, stable: set[str]) -> bool:
        security = current.get(ticker)
        return ticker in stable and security is not None and security.is_identity_verified

    needs_placeholder = sorted({
        ticker for tickers, stable in zip(ticker_sets, continuous)
        for ticker in tickers if not is_current(ticker, stable)
    })
    placeholders = _placeholders(needs_placeholder) if needs_placeholder else {}
    written = 0
    for row, tickers, stable in zip(ordered, ticker_sets, continuous):
        snapshot = MembershipSnapshot.from_row({
            "index_code": INDEX_SP500,
            "effective_date": str(row["effective_date"]),
            "tickers": list(tickers),
            "member_count": row.get("member_count", len(tickers)),
            "source": str(row.get("source") or "universe_membership"),
        })
        ids = [
            current[ticker].security_id if is_current(ticker, stable) else placeholders[ticker]
            for ticker in snapshot.tickers
        ]
        written += repository.record_membership(
            snapshot, source_hash=str(row["source_hash"]), security_ids=ids,
        )
    return written


def _placeholders(tickers: list[str]) -> dict[str, int]:
    """ticker마다 자리표시 종목 ID. 없으면 만든다."""
    db = _db()
    rows = db.select_in_chunks(
        schema=SCHEMA, table=T_SECURITIES, columns="security_id,ticker,is_identity_verified,is_active_listing",
        filter_column="ticker", values=tickers, order_by="ticker,security_id",
    )
    found: dict[str, int] = {}
    for row in rows:
        if not row.get("is_identity_verified") and not row.get("is_active_listing"):
            found.setdefault(str(row["ticker"]), int(row["security_id"]))
    missing = [ticker for ticker in tickers if ticker not in found]
    if missing:
        for start in range(0, len(missing), 500):
            db.table(SCHEMA, T_SECURITIES).insert(
                [_placeholder(ticker) for ticker in missing[start:start + 500]]
            ).execute()
        return _placeholders_existing(tickers)
    return found


def _placeholders_existing(tickers: list[str]) -> dict[str, int]:
    db = _db()
    rows = db.select_in_chunks(
        schema=SCHEMA, table=T_SECURITIES, columns="security_id,ticker,is_identity_verified,is_active_listing",
        filter_column="ticker", values=tickers, order_by="ticker,security_id",
    )
    found: dict[str, int] = {}
    for row in rows:
        if not row.get("is_identity_verified") and not row.get("is_active_listing"):
            found.setdefault(str(row["ticker"]), int(row["security_id"]))
    unresolved = sorted(set(tickers) - set(found))
    if unresolved:
        raise RuntimeError(f"placeholder securities were not created: {unresolved[:10]}")
    return found


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
