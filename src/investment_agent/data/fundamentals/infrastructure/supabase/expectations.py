"""시장 예상치·발표 일정·애널리스트 커버리지 저장소 구현.

세 표 모두 상태가 바뀔 때만 새 버전을 쓴다(`domain/services/state_versions.py`). 같은 상태를
다시 보면 그 버전의 `last_seen_at`만 옮긴다. 보존 기간으로 옛 스냅샷을 지우는 정리는 없다 —
버전 행은 바뀐 사건만 남으므로 지울 반복이 없고, 발표 전 예상 이력은 다시 받을 수 없다.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from investment_agent.data.fundamentals.domain.filing import filing_available_at
from investment_agent.data.fundamentals.domain.services.state_versions import plan_versions
from investment_agent.data.universe.domain.predecessors import with_predecessors

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
        .select("security_id,ticker,cik").in_("ticker", chunk).eq("is_active_listing", True),
        tickers,
        order_by="ticker",
        paged_reader=select_all_paged,
    )
    # 한 회사의 보통주가 둘(GOOG/GOOGL)이면 회계력도 둘 다에 붙인다.
    by_cik: dict[str, list[str]] = defaultdict(list)
    for row in securities:
        if row.get("cik"):
            by_cik[str(row["cik"])].append(str(row["ticker"]).upper())
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
    return [{**row, "ticker": ticker} for row in rows for ticker in by_cik[str(row["cik"])]]


def _security_ids(tickers: list[str]) -> dict[str, int]:
    """현재 ticker의 security_id. 과거 자리표시 종목이 같은 ticker를 가져도 상장 종목 하나만 고른다."""
    rows = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("security_id,ticker").in_("ticker", chunk).eq("is_active_listing", True),
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


_ESTIMATE_KEY = ("security_id", "target_fiscal_year", "target_fiscal_period", "source", "snapshot_kind")
_ESTIMATE_VALUES = (
    "target_period_end", "eps_basis", "currency", "eps_avg", "eps_low", "eps_high", "eps_analysts",
    "revenue_avg", "revenue_low", "revenue_high", "revenue_analysts",
    "revisions_up_7d", "revisions_up_30d", "revisions_down_7d", "revisions_down_30d",
)
_ESTIMATE_PK = "security_id,target_fiscal_year,target_fiscal_period,source,snapshot_kind,snapshot_date"
_SCHEDULE_KEY = ("security_id", "target_fiscal_year", "target_fiscal_period", "source")
_SCHEDULE_VALUES = ("target_period_end", "expected_report_at", "expected_session", "is_estimated")
_SCHEDULE_PK = "security_id,target_fiscal_year,target_fiscal_period,source,snapshot_date"
_ANALYST_KEY = ("security_id", "source")
_ANALYST_VALUES = (
    "target_mean", "target_median", "target_high", "target_low",
    "strong_buy", "buy", "hold", "sell", "strong_sell",
)
_ANALYST_PK = "security_id,source,snapshot_date"
# DB가 계산하거나 찍는 컬럼. 확인(last_seen_at) 갱신 때 되돌려 보내지 않는다.
_GENERATED = frozenset({"expected_report_date"})


def _write_versions(table: str, rows: list[dict], *, key: tuple, values: tuple, pk: str,
                    defaults: Mapping[str, object] | None = None) -> int:
    """상태가 바뀐 행만 넣고, 같은 상태는 기존 버전의 last_seen_at만 옮긴다.

    돌려주는 수는 이번에 관측해 반영한 상태 수(새 버전 + 확인)다. 호출자는 이 수로 수집이
    무너졌는지 판정하므로, 값이 안 바뀐 날을 0건으로 세면 정상 실행이 실패로 보인다.
    """
    payload = [{**(defaults or {}), **row} for row in _with_security_id(rows)]
    if not payload:
        return 0
    ids = sorted({int(row["security_id"]) for row in payload})
    stored = select_paged_in_chunks(
        lambda chunk: sb.schema(_SCHEMA).table(table).select("*").in_("security_id", chunk),
        ids,
        order_by=pk,
        paged_reader=select_all_paged,
    )
    plan = plan_versions(payload, stored, key_fields=key, value_fields=values,
                         now=datetime.now(timezone.utc))
    confirmations = [{k: v for k, v in row.items() if k not in _GENERATED} for row in plan.confirmations]
    _upsert(table, plan.new_rows, pk)
    _upsert(table, confirmations, pk)
    log.info("%s versions: new=%d confirmed=%d candidates=%d",
             table, len(plan.new_rows), len(confirmations), len(payload))
    return len(plan.new_rows) + len(confirmations)


def upsert_consensus(rows: list[dict]) -> int:
    """컨센서스 상태 버전. EPS 정의·통화를 원천이 말하지 않으면 unknown·NULL로 둔다."""
    return _write_versions(T_EARNINGS_ESTIMATES, rows, key=_ESTIMATE_KEY, values=_ESTIMATE_VALUES,
                           pk=_ESTIMATE_PK, defaults={"eps_basis": "unknown", "currency": None})


def upsert_schedules(rows: list[dict]) -> int:
    """발표 예정 상태 버전. 예정일이 움직였을 때만 새 행이 생긴다."""
    return _write_versions(T_EARNINGS_SCHEDULE, rows, key=_SCHEDULE_KEY, values=_SCHEDULE_VALUES,
                           pk=_SCHEDULE_PK)


def upsert_analyst_snapshots(rows: list[dict]) -> int:
    """목표주가·투자의견 분포 상태 버전."""
    return _write_versions(T_ANALYST_SNAPSHOTS, rows, key=_ANALYST_KEY, values=_ANALYST_VALUES,
                           pk=_ANALYST_PK)


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
        .eq("snapshot_kind", "captured_live"),
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


_FILING_COLUMNS = "accession_no,cik,filing_date,available_at,form_type,report_date"
_PERIODIC_FORMS = ("10-Q", "10-Q/A", "10-K", "10-K/A")


def _disclosures_for(rows: Sequence[dict]) -> dict[tuple[str, str], dict]:
    """(cik, 기간말)마다 그 기간을 처음 공개한 공시와 마지막으로 반영한 공시.

    재무 행은 기간마다 하나이고 `accession_no`는 마지막으로 값을 덮은 공시(정정이면 /A)다.
    과거 시점 조회는 그 기간이 **처음** 공개된 날로 잘라야 한다 — 정정일로 자르면 원본
    공시일과 정정일 사이에 그 기간이 통째로 사라진다. 처음 공개한 공시는 같은 CIK에서
    `report_date`가 기간말인 가장 이른 정기공시다.
    """
    if not rows:
        return {}
    accessions = sorted({str(row["accession_no"]) for row in rows})
    own = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS)
        .select(_FILING_COLUMNS).in_("accession_no", chunk),
        accessions, order_by="accession_no", paged_reader=select_all_paged,
    )
    periodic = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS)
        .select(_FILING_COLUMNS).in_("cik", chunk).in_("form_type", list(_PERIODIC_FORMS)),
        sorted({str(row["cik"]) for row in rows}), order_by="cik,filing_date,accession_no",
        paged_reader=select_all_paged,
    )
    return disclosures_by_period(rows, [*own, *periodic])


def disclosures_by_period(
    rows: Sequence[dict], filings: Sequence[dict]
) -> dict[tuple[str, str], dict]:
    """`_disclosures_for`의 순수 부분. DB 없이 검증한다."""
    by_accession = {str(row["accession_no"]): row for row in filings}
    by_period: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for filing in filings:
        if filing.get("report_date") and str(filing.get("form_type")) in _PERIODIC_FORMS:
            by_period[(str(filing["cik"]).zfill(10), str(filing["report_date"])[:10])].append(filing)
    result: dict[tuple[str, str], dict] = {}
    for row in rows:
        latest = by_accession.get(str(row["accession_no"]))
        if latest is None:
            raise ValueError("financial row has no filing provenance")
        key = (str(row["cik"]).zfill(10), str(row["period_end"])[:10])
        candidates = [latest, *by_period.get(key, [])]
        first = min(
            (item for item in candidates if item.get("filing_date")),
            key=lambda item: (str(item["filing_date"]), str(item.get("available_at") or "")),
        )
        result[key] = {"first": first, "latest": latest}
    return result


def _tickers_by_cik(securities: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """CIK → ticker들. 지주회사 재편 전 제출자의 CIK도 같은 ticker로 이어 준다(`universe.domain.predecessors`)."""
    tickers_by_cik: dict[str, list[str]] = defaultdict(list)
    for row in securities:
        if row.get("cik"):
            tickers_by_cik[str(row["cik"]).zfill(10)].append(str(row["ticker"]).upper())
    for predecessor, current in with_predecessors(list(tickers_by_cik)).items():
        if predecessor != current:
            tickers_by_cik[predecessor] = list(tickers_by_cik[current])
    return tickers_by_cik


def _financial_rows(ciks: Sequence[str]) -> list[dict]:
    return select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
        .select("*").in_("cik", chunk),
        sorted(ciks), order_by="cik,period_end",
        paged_reader=select_all_paged,
    )


def _fundamental_rows(
    ticker: str,
    as_of_at: datetime,
    *,
    include_available_at: bool,
    limit: int,
) -> list[dict]:
    """CIK 재무 버전과 공시 provenance를 한 ticker의 시점 읽기 모델로 투영한다."""
    securities = select_all_paged(
        lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("ticker,cik,is_active_listing").eq("ticker", ticker),
        order_by="ticker",
    )
    securities = [row for row in securities if row.get("cik")]
    if not securities:
        return []
    security = max(securities, key=lambda row: bool(row.get("is_active_listing")))
    rows = _financial_rows(list(with_predecessors([str(security["cik"])])))
    return _project_fundamental_rows(
        ticker, rows, _disclosures_for(rows), as_of_at,
        include_available_at=include_available_at, limit=limit,
    )


def _project_fundamental_rows(
    ticker: str,
    rows: Sequence[dict],
    disclosures: Mapping[tuple[str, str], dict],
    as_of_at: datetime,
    *,
    include_available_at: bool,
    limit: int,
) -> list[dict]:
    """cutoff 시점에 이미 공개돼 있던 회계기간의 재무 행만 남긴다.

    기간의 공개 시점은 그 기간을 처음 보고한 공시다. `include_available_at`이면 우리
    수집기가 그 공시를 손에 넣은 시각까지 cutoff 이전이어야 한다(운영 재현). 아니면 SEC
    제출일의 공개 규칙(`filing_available_at`)만 본다(원천 기준 연구). 값은 정정이 반영된
    현재 값이다 — 정정이 cutoff 뒤에 나왔어도 소급된다(스키마 머리주석 참고).
    """
    cutoff = _utc_iso(as_of_at)
    cutoff_date = as_of_at.date().isoformat()
    result: list[dict] = []
    for row in rows:
        disclosure = disclosures.get((str(row["cik"]).zfill(10), str(row["period_end"])[:10]))
        if disclosure is None:
            raise ValueError("financial row has no filing provenance")
        first = disclosure["first"]
        filed_at = str(first.get("filing_date") or "")[:10]
        if not filed_at or filed_at > cutoff_date:
            continue
        if not include_available_at and filing_available_at(filed_at) > as_of_at:
            # 원천 기준 재현에는 수집 시각이 없으므로 제출일의 공개 규칙만이 경계다.
            # 날짜만 비교하면 그날 장 마감 뒤 나온 공시를 그날 아침에 쓴다.
            continue
        if include_available_at and (
            not first.get("available_at")
            or _utc_iso(parse_datetime(first["available_at"])) > cutoff
        ):
            continue
        result.append({
            **row,
            "ticker": str(ticker).upper(),
            "filed_at": filed_at,
            "filing_date": filed_at,
            "available_at": first.get("available_at"),
            "form_type": disclosure["latest"].get("form_type"),
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
        .select("ticker,cik").in_("ticker", chunk).eq("is_active_listing", True),
        symbols, order_by="ticker", paged_reader=select_all_paged,
    )
    tickers_by_cik = _tickers_by_cik(securities)
    if not tickers_by_cik:
        return []
    financials = _financial_rows(list(tickers_by_cik))
    disclosures = _disclosures_for(financials)
    # CIK 하나가 여러 ticker로 갈라질 수 있다 — 저장 identity는 CIK이고 fan-out은
    # 읽기 경계의 몫이다.
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for row in financials:
        for ticker in tickers_by_cik[str(row["cik"]).zfill(10)]:
            by_ticker[ticker].append(row)
    result: list[dict] = []
    for ticker, rows in by_ticker.items():
        result.extend(_project_fundamental_rows(
            ticker, rows, disclosures, as_of_at, include_available_at=True, limit=limit,
        ))
    return result


def securities_fundamentals_filed_before(
    tickers: Sequence[str], as_of_at: datetime, *, limit: int = 12
) -> list[dict]:
    """여러 종목의 canonical 재무를 SEC 제출일 공개 규칙으로 한 번에 읽는다."""
    symbols = sorted({str(value).upper() for value in tickers})
    if not symbols:
        return []
    securities = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("ticker,cik").in_("ticker", chunk).eq("is_active_listing", True),
        symbols, order_by="ticker", paged_reader=select_all_paged,
    )
    tickers_by_cik = _tickers_by_cik(securities)
    if not tickers_by_cik:
        return []
    financials = _financial_rows(list(tickers_by_cik))
    disclosures = _disclosures_for(financials)
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for row in financials:
        for ticker in tickers_by_cik[str(row["cik"]).zfill(10)]:
            by_ticker[ticker].append(row)
    return [
        projected
        for ticker, rows in by_ticker.items()
        for projected in _project_fundamental_rows(
            ticker, rows, disclosures, as_of_at, include_available_at=False, limit=limit,
        )
    ]


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
        .eq("snapshot_kind", "captured_live")
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


def observed_consensus_for_tickers_as_of(
    tickers: Sequence[str], as_of_at: datetime, *, limit: int = 12
) -> dict[str, list[dict]]:
    """여러 종목의 실제 관측 컨센서스를 한 번에 읽고 ticker별 최신 행으로 자른다."""
    symbols = sorted({str(value).upper() for value in tickers})
    by_ticker = _security_ids(symbols)
    output: dict[str, list[dict]] = {ticker: [] for ticker in symbols}
    if not by_ticker:
        return output
    tickers_by_id: dict[int, list[str]] = defaultdict(list)
    for ticker, security_id in by_ticker.items():
        tickers_by_id[int(security_id)].append(ticker)
    rows = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_EARNINGS_ESTIMATES)
        .select("*").in_("security_id", chunk)
        .eq("snapshot_kind", "captured_live")
        .lte("snapshot_date", as_of_at.date().isoformat()),
        sorted(tickers_by_id), order_by="snapshot_date,security_id", paged_reader=select_all_paged,
    )
    for row in rows:
        collected_at = row.get("collected_at")
        if collected_at and parse_datetime(str(collected_at)) > as_of_at:
            continue
        for ticker in tickers_by_id.get(int(row["security_id"]), []):
            output[ticker].append({**row, "ticker": ticker})
    for ticker in output:
        output[ticker].sort(key=lambda row: str(row.get("snapshot_date") or ""), reverse=True)
        output[ticker] = output[ticker][:limit]
    return output
