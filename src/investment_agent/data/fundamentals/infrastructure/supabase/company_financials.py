"""기업 전체 재무 수집을 위한 Supabase 저장소 구현."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from investment_agent.data.universe.watchlists import db as alerts_db
from investment_agent.platform.logging import get_logger
from investment_agent.platform.db.postgres import (
    chunk_values,
    sb,
    select_all_paged,
    select_paged_in_chunks,
)
from investment_agent.data.fundamentals.domain.filings import filing_row
from investment_agent.data.fundamentals.domain.taxonomy import gaap_concepts as concepts
from investment_agent.data.fundamentals.domain.taxonomy.financial_columns import ALL_WIDE_COLUMNS

# --- DB 식별자 (SSOT) ---------------------------------------------------
SCHEMA_FUNDAMENTALS = "fundamentals"
SCHEMA_UNIVERSE = "universe"
T_FINANCIALS = "financials"  # 뷰: 기간별 최신 공시 버전
T_FINANCIAL_VERSIONS = "financial_versions"
T_FILINGS = "filings"
T_FILING_PROCESSING = "filing_processing"
T_EARNINGS_SCHEDULE = "earnings_schedule_versions"
T_SECURITIES = "securities"
T_ENTITIES = "entities"
# ----------------------------------------------------------------------


log = get_logger(__name__)

_UPSERT_BATCH = 250
# wide 행을 만드는 동안만 들고 다니는 키. financials에는 컬럼이 없다.
_MEMORY_ONLY_KEYS = frozenset({"source_manifest"})


def gating_universe() -> list[dict]:
    """Tracked ticker selectors with their CIK, for CLI boundary selection only.

    This is intentionally not a storage identity map. SEC facts are keyed by the
    ``cik`` returned here and persistence never fans a fact out to ``ticker``.
    """
    return select_all_paged(
        lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("ticker,cik")
        .eq("is_tracked", True)
        .not_.is_("cik", "null")
        .order("ticker"),
        order_by='ticker',
    )


def tracked_ciks() -> set[str]:
    """Return the entity gate for SEC CompanyFacts work exactly once per CIK."""
    rows = select_all_paged(
        lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("cik,ticker").eq("is_tracked", True)
        .not_.is_("cik", "null")
        .order("ticker"),
        order_by="ticker",
    )
    return {str(row["cik"]).zfill(10) for row in rows if row.get("cik")}


def ciks_for_tickers(tickers: set[str] | list[str]) -> set[str]:
    """Resolve ticker CLI selectors to their current CIKs without fan-out."""
    wanted = sorted({str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()})
    if not wanted:
        return set()
    rows = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("ticker,cik").in_("ticker", chunk).eq("is_tracked", True)
        .not_.is_("cik", "null"),
        wanted,
        order_by="ticker",
        paged_reader=select_all_paged,
    )
    found_tickers = {str(row["ticker"]) for row in rows}
    unknown = set(wanted) - found_tickers
    if unknown:
        raise ValueError(
            "requested tickers are not in the tracked CIK universe: "
            + ",".join(sorted(unknown))
        )
    return {str(row["cik"]).zfill(10) for row in rows}


def tickers_by_cik() -> dict[str, list[str]]:
    """현재 tracked security를 CIK별 표시 ticker 목록으로 반환한다."""
    out: dict[str, list[str]] = {}
    for row in gating_universe():
        cik = str(row.get("cik") or "").zfill(10)
        if cik:
            out.setdefault(cik, []).append(str(row["ticker"]))
    for tickers in out.values():
        tickers.sort()
    return out


def watchlist_tickers() -> set[str]:
    """알림 대상 관심종목. fast path가 훑을 범위를 정한다."""
    return {str(member["ticker"]) for member in alerts_db.active_members("fundamentals")}


def watchlist_expected_reports() -> list[dict]:
    """관심종목의 다음 발표 예정일 — 티커별 최신 일정 스냅샷 1건.

    시즌 게이트가 "지금 발표가 몰리는 구간인가"를 판단하는 유일한 입력이다.
    yfinance 유래라 자주 바뀌고 비어 있을 수 있어, 판정은
    `refresh_earnings_season.evaluate()`가 fail-open으로 처리한다.
    """
    tickers = sorted(watchlist_tickers())
    if not tickers:
        return []
    securities = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("security_id,ticker").in_("ticker", chunk).eq("is_active_listing", True),
        tickers,
        order_by="ticker",
        paged_reader=select_all_paged,
    )
    ids = [int(row["security_id"]) for row in securities]
    if not ids:
        return []
    ticker_by_id = {int(row["security_id"]): str(row["ticker"]) for row in securities}
    rows = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_EARNINGS_SCHEDULE)
        .select(
            "security_id,snapshot_date,expected_report_date,"
            "expected_report_at,expected_session,is_estimated"
        ).in_("security_id", chunk),
        ids,
        order_by="security_id,snapshot_date",
        paged_reader=select_all_paged,
    )
    latest: dict[str, dict] = {}
    for row in rows:
        ticker = ticker_by_id.get(int(row["security_id"]))
        if not ticker:
            continue
        row = {**row, "ticker": ticker}
        current = latest.get(ticker)
        if current is None or str(row["snapshot_date"]) > str(current["snapshot_date"]):
            latest[ticker] = row
    return [latest[ticker] for ticker in sorted(latest)]


def last_filed_map() -> dict[str, str]:
    """Latest filed_at already loaded per source CIK."""
    rows = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS)
        .select("cik,filing_date"),
        order_by="cik,filing_date",
    )
    latest: dict[str, str] = {}
    for row in rows:
        cik = str(row.get("cik") or "").zfill(10)
        filed = str(row.get("filing_date") or "")
        if cik and filed and filed > latest.get(cik, ""):
            latest[cik] = filed
    return latest


def filing_accessions(statuses: tuple[str, ...]) -> dict[str, set[str]]:
    """현재 매핑 버전의 지정 상태 accession_no을 source CIK별로 반환한다."""
    rows = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS)
        .table(T_FILING_PROCESSING)
        .select("accession_no,status")
        .eq("content_type", "company")
        .eq("mapping_version", concepts.SEMANTIC_POLICY_VERSION)
        .in_("status", list(statuses)),
        order_by="accession_no",
    )
    accessions = sorted({str(row["accession_no"]) for row in rows})
    if not accessions:
        return {}
    filings = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS)
        .select("accession_no,cik").in_("accession_no", chunk),
        accessions,
        order_by="cik,accession_no",
        paged_reader=select_all_paged,
    )
    cik_by_accession = {str(row["accession_no"]): str(row["cik"]).zfill(10) for row in filings}
    out: dict[str, set[str]] = {}
    for row in rows:
        accession_no = str(row["accession_no"])
        cik = cik_by_accession.get(accession_no)
        if cik:
            out.setdefault(cik, set()).add(accession_no)
    return out


def processed_filing_accessions() -> dict[str, set[str]]:
    """daily/backfill이 완료한 accession_no을 source CIK별로 반환한다."""
    return filing_accessions(("parsed", "empty", "unsupported", "superseded"))


def _filing_state_row(
    cik: str,
    filing,
    *,
    status: str,
    source: str,
    facts_count: int = 0,
    rows_count: int = 0,
) -> dict:
    return {
        "accession_no": filing.accession_no,
        "content_type": "company",
        "status": status,
        "mapping_version": concepts.SEMANTIC_POLICY_VERSION,
        "facts_count": facts_count,
        "rows_count": rows_count,
    }


def _ensure_filings(targets: Iterable[tuple[object, str]]) -> None:
    """공시 사실을 processing 상태보다 먼저 canonical filings에 기록한다."""
    rows = [filing_row(filing, cik) for filing, cik in targets]
    rows = [row for row in rows if row.get("accession_no") and row.get("filing_date")]
    for start in range(0, len(rows), _UPSERT_BATCH):
        sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS).upsert(
            rows[start:start + _UPSERT_BATCH], on_conflict="accession_no"
        ).execute()


def _upsert_filing_states(rows: list[dict]) -> int:
    if not rows:
        return 0
    total = 0
    for i in range(0, len(rows), _UPSERT_BATCH):
        chunk = rows[i:i + _UPSERT_BATCH]
        sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILING_PROCESSING).upsert(
            chunk,
            on_conflict="accession_no,content_type,mapping_version",
        ).execute()
        total += len(chunk)
    return total


def upsert_filings(filings: Iterable[object]) -> int:
    """재무 사실보다 먼저 공시 원장을 만든다(모든 자식 행의 FK 부모)."""
    rows = [filing_row(filing) for filing in filings]
    if not rows:
        return 0
    total = 0
    for start in range(0, len(rows), _UPSERT_BATCH):
        chunk = rows[start:start + _UPSERT_BATCH]
        sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS).upsert(
            chunk, on_conflict="accession_no"
        ).execute()
        total += len(chunk)
    return total


def mark_empty_filing_targets(
    targets: list[tuple[object, str]],
    *,
    source: str,
) -> int:
    """허용된 표준 fact가 없는 공시를 정상 완료(empty)로 기록한다."""
    _ensure_filings(targets)
    return _upsert_filing_states([
        _filing_state_row(cik, filing, status="empty", source=source)
        for filing, cik in targets
    ])


def mark_superseded_filing_targets(
    targets: list[tuple[object, str]],
    *,
    source: str,
) -> int:
    """현재 CIK의 동일 기간이 대신하는 전임 CIK 공시를 terminal로 기록한다."""
    _ensure_filings(targets)
    return _upsert_filing_states([
        _filing_state_row(cik, filing, status="superseded", source=source)
        for filing, cik in targets
    ])


def mark_processed_filing_targets(
    targets: list[tuple[object, str, int, int]],
    *,
    source: str,
) -> int:
    """공시별 fact 수를 보존하면서 완료 상태를 한 번에 기록한다."""
    rows: list[dict] = []
    for filing, cik, facts_count, rows_count in targets:
        rows.append(
            _filing_state_row(
                cik, filing, status="parsed", source=source,
                facts_count=facts_count, rows_count=rows_count,
            )
        )
    _ensure_filings([(filing, cik) for filing, cik, _, _ in targets])
    return _upsert_filing_states(rows)


def reconcile_wide_history(cik_ceiling: dict[str, str], floor: date) -> int:
    """전체 재처리 뒤 현재 매핑 버전이 아닌 행과 보관 기간 밖의 행을 제거한다.

    같은 공시를 현재 매핑 버전으로 다시 처리했을 때만 부른다. 옛 매핑 버전 행을 남기면
    최신 뷰가 처리 시각으로 고르긴 하지만, 재처리 범위 밖 기간과 섞여 한 시계열에 두 규칙이
    공존한다. 정정 공시(다른 accession)의 이전 버전은 지우지 않는다.
    """
    if not cik_ceiling:
        return 0
    removed = 0
    ciks = list(cik_ceiling)
    for cik, ceiling in cik_ceiling.items():
        stale = (
            sb.schema(SCHEMA_FUNDAMENTALS)
            .table(T_FINANCIAL_VERSIONS)
            .delete()
            .eq("cik", cik)
            .neq("mapping_version", concepts.SEMANTIC_POLICY_VERSION)
            .lte("period_end", ceiling)
            .execute()
            .data
            or []
        )
        removed += len(stale)
    for chunk in chunk_values(ciks, _UPSERT_BATCH):
        expired = (
            sb.schema(SCHEMA_FUNDAMENTALS)
            .table(T_FINANCIAL_VERSIONS)
            .delete()
            .in_("cik", chunk)
            .lt("period_end", floor.isoformat())
            .execute()
            .data
            or []
        )
        removed += len(expired)
    log.info("wide history reconciled: ciks=%d removed=%d", len(ciks), removed)
    return removed


def ciks_missing_financials() -> list[str]:
    """현재 추적 security에 연결됐지만 core fundamentals가 없는 CIK."""
    tracked = tracked_ciks()
    if not tracked:
        return []
    rows = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
        .select("cik"),
        order_by="cik",
    )
    present = {str(row["cik"]).zfill(10) for row in rows if row.get("cik")}
    return sorted(tracked - present)


def upsert_core_wide(rows: list[dict]) -> int:
    """공시별 재무 버전을 저장한다.

    키는 (cik, period_end, fiscal_period, accession_no, mapping_version)이다. 정정 공시는
    새 행이 되어 정정 전 숫자가 남고, 같은 공시를 같은 매핑 버전으로 다시 처리하면 같은
    행을 갱신한다. `source_manifest`는 컬럼별 채택 근거를 담은 메모리 전용 값이라 떼어 낸다
    — 남기면 PostgREST가 payload 전체를 PGRST204로 거절한다.
    """
    if not rows:
        return 0
    invalid = [
        row for row in rows
        if (
            not row.get("cik")
            or not row.get("period_end")
            or not row.get("accession_no")
            or "ticker" in row
        )
    ]
    if invalid:
        raise ValueError(
            "financial version rows require cik, period_end, accession_no and no ticker"
        )
    persisted = {
        "cik", "period_end", "accession_no", "fiscal_year", "fiscal_period",
        "mapping_version", "common_equity_scope", "is_liabilities_derived",
        *ALL_WIDE_COLUMNS,
    }
    payload = [
        {
            key: value
            for key, value in {
                **row,
                "mapping_version": row.get("mapping_version") or concepts.SEMANTIC_POLICY_VERSION,
            }.items()
            if key not in _MEMORY_ONLY_KEYS and key in persisted
        }
        for row in rows
    ]
    upserted = 0
    for start in range(0, len(payload), _UPSERT_BATCH):
        chunk = payload[start:start + _UPSERT_BATCH]
        sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIAL_VERSIONS).upsert(
            chunk, on_conflict="cik,period_end,fiscal_period,accession_no,mapping_version"
        ).execute()
        upserted += len(chunk)
    log.info("financial versions upserted: written=%d", upserted)
    return upserted


def _issue_key(row: dict) -> str:
    """로그에서 같은 데이터 이상을 묶어 찾을 수 있는 결정적 키를 만든다."""
    detail = row.get("detail") or {}
    column_key = str(detail.get("column_key") or row.get("reason") or "unknown")
    return ":".join((
        str(row.get("cik") or "?"),
        str(row.get("fiscal_year") or "?"),
        str(row.get("fiscal_period") or "?"),
        column_key,
    ))


def report_anomalies(anomalies: list[dict]) -> int:
    """저장에서 제외한 데이터 이상을 로그로 남기고 DB에는 쓰지 않는다."""
    for row in anomalies:
        log.warning(
            "fundamentals anomaly rejected: key=%s reason=%s detail=%s",
            _issue_key(row),
            row.get("reason") or "unknown",
            row.get("detail") or {},
        )
    if anomalies:
        log.warning("fundamentals anomalies rejected: count=%d", len(anomalies))
    return len(anomalies)
