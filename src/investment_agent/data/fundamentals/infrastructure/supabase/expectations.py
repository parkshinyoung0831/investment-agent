"""시장 예상치·발표 일정·애널리스트 커버리지 저장소 구현."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from investment_agent.platform.logging import get_logger
from investment_agent.platform.db.postgres import sb, select_all_paged, select_paged_in_chunks
from investment_agent.platform.serialization import parse_datetime

# --- DB 식별자 (SSOT) ---------------------------------------------------
# 문자열을 흩뿌리면 개명·오타가 런타임 PGRST 404로만 드러난다. 여기서만 바꾼다.
SCHEMA_FUNDAMENTALS = "fundamentals"
SCHEMA_UNIVERSE = "universe"
T_EARNINGS_ESTIMATES = "earnings_estimates"
T_EARNINGS_SCHEDULE = "earnings_schedule_versions"
T_ANALYST_SNAPSHOTS = "analyst_consensus_snapshots"
T_FINANCIALS = "financials"
T_FILINGS = "filings"
T_SECURITIES = "securities"
# ----------------------------------------------------------------------


log = get_logger(__name__)

_SCHEMA = "fundamentals"
UPSERT_BATCH = 500


def universe_tracked() -> list[str]:
    """현재 수집 대상 종목코드."""
    rows = select_all_paged(
        lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES).select("ticker").eq("is_tracked", True),
        order_by="ticker",
    )
    return sorted({str(row["ticker"]) for row in rows})


def watchlist_tickers() -> list[str]:
    """실적 알림 관심종목과 같은 수집 대상."""
    from investment_agent.data.universe.watchlists import db as alerts_db

    return sorted({str(row["ticker"]) for row in alerts_db.active_members("fundamentals")})


def fiscal_periods(tickers: list[str]) -> list[dict]:
    """예상치를 붙일 실제 회계기간 이력과 다음 기간 추정의 기준점."""
    if not tickers:
        return []
    securities = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("security_id,ticker,cik").in_("ticker", chunk),
        tickers,
        order_by="ticker",
        paged_reader=select_all_paged,
    )
    by_cik = {
        str(row["cik"]): str(row["ticker"]).upper()
        for row in securities if row.get("cik")
    }
    if not by_cik:
        return []
    rows = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
        .select("cik,fiscal_year,fiscal_period,period_end")
        .in_("cik", chunk).in_("fiscal_period", ["Q1", "Q2", "Q3", "Q4"]),
        sorted(by_cik),
        order_by="cik,fiscal_year,fiscal_period,period_end",
        paged_reader=select_all_paged,
    )
    return [{**row, "ticker": by_cik[str(row["cik"])]} for row in rows]


def _security_ids(tickers: list[str]) -> dict[str, int]:
    rows = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("security_id,ticker").in_("ticker", chunk),
        sorted(set(tickers)),
        order_by="ticker",
        paged_reader=select_all_paged,
    )
    return {str(row["ticker"]).upper(): int(row["security_id"]) for row in rows}


def _with_security_id(rows: list[dict], *, required: bool = True) -> list[dict]:
    tickers = sorted({str(row.get("ticker") or "").upper() for row in rows if row.get("ticker")})
    by_ticker = _security_ids(tickers)
    payload: list[dict] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        security_id = by_ticker.get(ticker)
        if security_id is None:
            if required:
                raise ValueError(f"ticker is not present in universe.securities: {ticker!r}")
            continue
        payload.append({
            key: value
            for key, value in {**row, "security_id": security_id}.items()
            if key != "ticker"
        })
    return payload


def _upsert(table: str, rows: list[dict], conflict: str) -> int:
    if not rows:
        return 0
    total = 0
    for start in range(0, len(rows), UPSERT_BATCH):
        chunk = rows[start:start + UPSERT_BATCH]
        sb.schema(_SCHEMA).table(table).upsert(chunk, on_conflict=conflict).execute()
        total += len(chunk)
    return total


def upsert_consensus(rows: list[dict]) -> int:
    return _upsert(T_EARNINGS_ESTIMATES, _with_security_id(rows),
                   "security_id,target_fiscal_year,target_fiscal_period,snapshot_date,source,snapshot_kind")


def upsert_schedules(rows: list[dict]) -> int:
    """관측일별 발표 예정일. 예정일은 자주 바뀌므로 스냅샷으로 쌓는다."""
    return _upsert(
        T_EARNINGS_SCHEDULE, _with_security_id(rows),
        "security_id,target_fiscal_year,target_fiscal_period,snapshot_date,source",
    )


def upsert_analyst_snapshots(rows: list[dict]) -> int:
    """목표주가와 투자의견 분포. 종목·관측일당 한 행이다."""
    return _upsert(T_ANALYST_SNAPSHOTS, _with_security_id(rows), "security_id,snapshot_date,source")


def prune_earnings_estimates(days: int = 1095) -> dict:
    """복구 가능한 consensus만 보존기간 밖에서 정리한다."""
    if days < 1:
        raise ValueError("days must be at least 1")
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=days)
    response = sb.schema(SCHEMA_FUNDAMENTALS).table(T_EARNINGS_ESTIMATES).delete(
        count="exact", returning="minimal"
    ).lt("snapshot_date", cutoff.isoformat()).execute()
    return {"deleted": int(response.count or 0)}


RPC_PRUNE_EXPECTATIONS = "prune_expectation_snapshots"
# 발표가 끝났어도 이 기간 안쪽은 통째로 남긴다 — 그래야 그 시점 판단을 재현할 수 있다.
PRUNE_RECENT_DAYS = 180


def prune_expectation_snapshots(recent_days: int = PRUNE_RECENT_DAYS) -> dict:
    """발표가 끝난 기간의 스냅샷을 계약에 필요한 한 건씩만 남긴다.

    나이로만 자르면 아직 발표 안 한 분기의 드리프트가 사라지고, 반대로 오래된
    분기의 매일치가 그대로 남는다. 무엇이 계속 읽히는지로 자른다 — 서프라이즈가
    집는 "발표일 직전 마지막 스냅샷"은 나이와 무관하게 남긴다.
    """
    if recent_days < 1:
        raise ValueError("recent_days must be at least 1")
    rows = sb.schema(SCHEMA_FUNDAMENTALS).rpc(
        RPC_PRUNE_EXPECTATIONS, {"p_recent_days": recent_days}
    ).execute().data or []
    row = rows[0] if isinstance(rows, list) and rows else (rows if isinstance(rows, dict) else {})
    return {
        "estimates_deleted": int(row.get("estimates_deleted") or 0),
        "schedules_deleted": int(row.get("schedules_deleted") or 0),
        "consensus_deleted": int(row.get("consensus_deleted") or 0),
    }


def latest_analyst_snapshots(tickers: list[str]) -> list[dict]:
    """종목·원천별 직전 커버리지 값만 DB에서 읽는다."""
    if not tickers:
        return []
    by_ticker = _security_ids(tickers)
    if not by_ticker:
        return []
    ticker_by_id = {value: key for key, value in by_ticker.items()}
    rows = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_ANALYST_SNAPSHOTS)
        .select("*").in_("security_id", chunk),
        list(ticker_by_id),
        order_by="security_id,snapshot_date",
        paged_reader=select_all_paged,
    )
    latest: dict[tuple[int, str], dict] = {}
    for row in rows:
        key = (int(row["security_id"]), str(row.get("source") or ""))
        if key not in latest or str(row["snapshot_date"]) > str(latest[key]["snapshot_date"]):
            latest[key] = row
    return [{**row, "ticker": ticker_by_id[int(row["security_id"])]} for row in latest.values()]


def tickers_missing_consensus(tickers: list[str]) -> set[str]:
    """실제 관측값이 한 번도 없는 종목만 재구성 시드를 만든다."""
    if not tickers:
        return set()
    by_ticker = _security_ids(tickers)
    if not by_ticker:
        return set(tickers)
    rows = select_paged_in_chunks(
        lambda chunk: sb.schema(_SCHEMA).table(T_EARNINGS_ESTIMATES)
        .select("security_id").in_("security_id", chunk)
        .eq("snapshot_kind", "observed"),
        list(by_ticker.values()),
        order_by="security_id",
        paged_reader=select_all_paged,
    )
    observed = {int(row["security_id"]) for row in rows}
    return {ticker for ticker, security_id in by_ticker.items() if security_id not in observed}


# --- 판단 evidence가 읽는 point-in-time 조회 --------------------------------


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    return value.astimezone(timezone.utc).isoformat()


def _fundamental_rows(
    ticker: str,
    as_of_at: datetime,
    *,
    include_available_at: bool,
    limit: int,
) -> list[dict]:
    """CIK canonical 재무와 source filing provenance를 ticker 읽기 모델로 투영한다."""
    securities = select_all_paged(
        lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("ticker,cik").eq("ticker", ticker),
        order_by="ticker",
    )
    if not securities or not securities[0].get("cik"):
        return []
    cik = str(securities[0]["cik"]).zfill(10)
    financials = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
        .select("*").eq("cik", cik),
        order_by="period_end,source_accession_no",
    )
    accessions = sorted({str(row["source_accession_no"]) for row in financials})
    filings = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS)
        .select("accession_no,filing_date,available_at,form_type").in_("accession_no", chunk),
        accessions, order_by="accession_no", paged_reader=select_all_paged,
    ) if accessions else []
    provenance = {row["accession_no"]: row for row in filings}
    return _project_fundamental_rows(
        ticker, financials, provenance, as_of_at,
        include_available_at=include_available_at, limit=limit,
    )


def _project_fundamental_rows(
    ticker: str,
    financials: Sequence[dict],
    provenance: Mapping[str, dict],
    as_of_at: datetime,
    *,
    include_available_at: bool,
    limit: int,
) -> list[dict]:
    """CIK canonical 재무를 한 ticker의 시점 읽기 모델로 투영한다."""
    cutoff = _utc_iso(as_of_at)
    cutoff_date = as_of_at.date().isoformat()
    result: list[dict] = []
    for row in financials:
        filed_at = str(row.get("source_filing_date") or "")
        if not filed_at or filed_at > cutoff_date:
            continue
        filing = provenance.get(row["source_accession_no"])
        if filing is None:
            raise ValueError("canonical financial row has no filing provenance")
        if include_available_at and (not filing.get("available_at") or _utc_iso(parse_datetime(filing["available_at"])) > cutoff):
            continue
        result.append({
            **row,
            "accession_no": row.get("source_accession_no"),
            "ticker": str(ticker).upper(),
            "filed_at": filed_at,
            "available_at": filing.get("available_at"),
            "form_type": filing.get("form_type"),
        })
    result.sort(key=lambda row: (
        str(row.get("filed_at") or ""),
        str(row.get("period_end") or ""),
        str(row.get("accession_no") or ""),
    ), reverse=True)
    return result[:limit]


def securities_fundamentals_as_of(
    tickers: Sequence[str], as_of_at: datetime, *, limit: int = 12
) -> list[dict]:
    """여러 종목의 canonical 재무 행을 한 번에 읽는다.

    종목마다 `security_fundamentals_as_of`를 부르면 종목당 왕복이 세 번이다
    (증권→재무→공시). 500종목이면 1,500번이고, 실측 43초가 여기였다.
    """
    symbols = sorted({str(value).upper() for value in tickers})
    if not symbols:
        return []
    securities = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("ticker,cik").in_("ticker", chunk),
        symbols, order_by="ticker", paged_reader=select_all_paged,
    )
    tickers_by_cik: dict[str, list[str]] = defaultdict(list)
    for row in securities:
        if row.get("cik"):
            tickers_by_cik[str(row["cik"]).zfill(10)].append(str(row["ticker"]).upper())
    if not tickers_by_cik:
        return []
    financials = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
        .select("*").in_("cik", chunk),
        sorted(tickers_by_cik), order_by="cik,period_end,source_accession_no",
        paged_reader=select_all_paged,
    )
    accessions = sorted({str(row["source_accession_no"]) for row in financials})
    filings = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS)
        .select("accession_no,filing_date,available_at,form_type").in_("accession_no", chunk),
        accessions, order_by="accession_no", paged_reader=select_all_paged,
    ) if accessions else []
    provenance = {row["accession_no"]: row for row in filings}
    # CIK 하나가 여러 ticker로 갈라질 수 있다 — 저장 identity는 CIK이고 fan-out은
    # 읽기 경계의 몫이다.
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for row in financials:
        for ticker in tickers_by_cik[str(row["cik"]).zfill(10)]:
            by_ticker[ticker].append(row)
    result: list[dict] = []
    for ticker, rows in by_ticker.items():
        result.extend(_project_fundamental_rows(
            ticker, rows, provenance, as_of_at, include_available_at=True, limit=limit,
        ))
    return result


def security_fundamentals_as_of(ticker: str, as_of_at: datetime, *, limit: int = 12) -> list[dict]:
    """공시일 cutoff까지의 canonical 재무 행."""
    return _fundamental_rows(
        ticker, as_of_at, include_available_at=True, limit=limit
    )


def security_fundamentals_filed_before(
    ticker: str, as_of_at: datetime, *, limit: int = 12
) -> list[dict]:
    """공시일 cutoff까지의 최신 wide 행. 적재 시각은 보지 않는다."""
    return _fundamental_rows(
        ticker, as_of_at, include_available_at=False, limit=limit
    )


def observed_consensus_as_of(ticker: str, as_of_at: datetime, *, limit: int = 12) -> list[dict]:
    """그 시점까지 실제로 수집돼 있던 관측 컨센서스 스냅샷."""
    ids = _security_ids([ticker])
    security_id = ids.get(str(ticker).upper())
    if security_id is None:
        return []
    rows = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_EARNINGS_ESTIMATES)
        .select("*").eq("security_id", security_id)
        .eq("snapshot_kind", "observed")
        .lte("snapshot_date", as_of_at.date().isoformat()),
        order_by="snapshot_date,security_id",
    )
    result = []
    for row in rows:
        collected_at = row.get("collected_at")
        if collected_at and parse_datetime(str(collected_at)) > as_of_at:
            continue
        result.append({**row, "ticker": str(ticker).upper()})
    result.sort(key=lambda row: str(row.get("snapshot_date") or ""), reverse=True)
    return result[:limit]
