"""세그먼트 공시와 압축 지표를 위한 Supabase 저장소 구현."""
from __future__ import annotations

from datetime import datetime, timezone

from collections import defaultdict
from collections.abc import Iterable, Sequence

from investment_agent.data.universe.watchlists import db as alerts_db
from investment_agent.operations.runtime import utc_now_iso
from investment_agent.platform.logging import get_logger
from investment_agent.platform.db.postgres import chunk_filter_values, sb, select_all_paged, select_paged_in_chunks
from investment_agent.data.fundamentals.domain.services.assess_segment_quality import assess_rows
from investment_agent.data.fundamentals.domain.taxonomy.segment_axes import SEGMENT_MAPPING_VERSION
from investment_agent.data.fundamentals.infrastructure.supabase import company_financials

# --- DB 식별자 (SSOT) ---------------------------------------------------
# 문자열을 흩뿌리면 개명·오타가 런타임 PGRST 404로만 드러난다. 여기서만 바꾼다.
SCHEMA_FUNDAMENTALS = "fundamentals"
SCHEMA_UNIVERSE = "universe"
T_FINANCIALS = "financials"
T_FILINGS = "filings"
T_FILING_PROCESSING = "filing_processing"
T_SEGMENT_METRICS = "segment_metrics"
T_SECURITIES = "securities"
CONTENT_SEGMENTS = "segments"
# ----------------------------------------------------------------------


MAPPING_VERSION = SEGMENT_MAPPING_VERSION

log = get_logger(__name__)

_SCHEMA = "fundamentals"
_METRICS_TABLE = T_SEGMENT_METRICS
_FILINGS_TABLE = T_FILINGS
_PROCESSING_TABLE = T_FILING_PROCESSING
_UPSERT_BATCH = 1000
# SEC accession_no은 보통 20자 안팎이다. CIK별 50개면 URL 인코딩 후에도
# PostgREST 요청 URL을 보수적인 수 KB 범위에 두면서 호출 수를 크게 줄인다.
_DELETE_ACCESSION_BATCH = 50
_KEY_FIELDS = ("cik", "accession_no", "fiscal_year", "fiscal_period", "segment_hash")
_METRICS_CONFLICT = ",".join(_KEY_FIELDS)
_SEGMENT_TYPES = frozenset({"business", "product", "geographic"})
_USABLE_QUALITY = frozenset({"verified", "partial"})
_COMPANY_BASELINE_COLUMNS = (
    "revenue",
    "gross_profit",
    "operating_income_loss",
    "pretax_income_loss",
    "net_income",
    "assets",
)
_ANNUAL_FLOW_BASELINE_COLUMNS = _COMPANY_BASELINE_COLUMNS[:-1]
_QUARTER_PERIODS = ("Q1", "Q2", "Q3", "Q4")


def _is_better(candidate: dict, current: dict | None) -> bool:
    if current is None:
        return True
    if bool(candidate.get("is_derived")) != bool(current.get("is_derived")):
        return not bool(candidate.get("is_derived"))
    return (
        str(candidate.get("reported_at") or ""),
        str(candidate.get("accession_no") or ""),
    ) > (
        str(current.get("reported_at") or ""),
        str(current.get("accession_no") or ""),
    )


def _dedupe(rows: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    by_key: dict[tuple, dict] = {}
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        if _is_better(row, by_key.get(key)):
            by_key[key] = row
    return list(by_key.values())


def tracked_ciks() -> set[str]:
    return company_financials.tracked_ciks()


def ciks_for_tickers(tickers: set[str] | list[str]) -> set[str]:
    return company_financials.ciks_for_tickers(tickers)


def watchlist_tickers() -> set[str]:
    """세그먼트 수집 대상 관심종목. fast path가 훑을 범위를 정한다.

    세그먼트는 별도 구독이 아니라 실적 카드의 한 단면이라 관심종목 옵트인을
    실적과 공유한다 — 축을 둘로 나누면 아무도 켜지 않는 설정이 하나 더 생긴다.
    """
    return {str(member["ticker"]) for member in alerts_db.active_members("fundamentals")}


def filing_accessions(
    statuses: tuple[str, ...],
    forms: Iterable[str] | None = None,
) -> dict[str, set[str]]:
    """현재 매핑 버전의 지정 상태 accession_no을 CIK별로 반환한다."""
    wanted = tuple(forms or ())

    def builder():
        query = (
            sb.schema(_SCHEMA).table(_PROCESSING_TABLE)
            .select("accession_no,status")
            .eq("content_type", CONTENT_SEGMENTS)
            .eq("mapping_version", MAPPING_VERSION)
        )
        query = query.in_("status", list(statuses))
        return query

    rows = select_all_paged(builder, order_by="accession_no")
    accessions = sorted({str(row["accession_no"]) for row in rows})
    if not accessions:
        return {}
    filings = select_paged_in_chunks(
        lambda chunk: sb.schema(_SCHEMA).table(_FILINGS_TABLE)
        .select("cik,accession_no,form_type").in_("accession_no", chunk),
        accessions,
        order_by="cik,accession_no",
        paged_reader=select_all_paged,
    )
    filing_by_accession = {str(row["accession_no"]): row for row in filings}
    out: dict[str, set[str]] = {}
    for row in rows:
        filing = filing_by_accession.get(str(row["accession_no"]))
        if filing and (not wanted or filing.get("form_type") in wanted):
            out.setdefault(str(filing["cik"]), set()).add(str(row["accession_no"]))
    return out


def existing_accessions(forms: Iterable[str] | None = None) -> dict[str, set[str]]:
    """CIK별 완료 accession_no. 실패는 저장하지 않아 자동으로 재시도된다."""
    return filing_accessions(("parsed", "empty", "unsupported"), forms)


def accessions_by_source(
    sources: tuple[str, ...],
    forms: Iterable[str] | None = None,
) -> dict[str, set[str]]:
    """지정 source로 적재된 accession_no을 CIK별로 반환한다."""
    wanted = tuple(forms or ())

    def builder():
        query = sb.schema(_SCHEMA).table(_FILINGS_TABLE).select(
            "cik,accession_no,form_type"
        ).in_("source", list(sources))
        if wanted:
            query = query.in_("form_type", list(wanted))
        return query.order("cik").order("accession_no")

    out: dict[str, set[str]] = {}
    for row in select_all_paged(builder, order_by="cik,accession_no"):
        out.setdefault(str(row["cik"]), set()).add(str(row["accession_no"]))
    return out


def _metric_key(row: dict) -> tuple[str, str, int, str, str]:
    return (
        str(row["cik"]),
        str(row["accession_no"]),
        int(row["fiscal_year"]),
        str(row["fiscal_period"]),
        str(row["segment_hash"]),
    )


def delete_stale_metrics_for_accessions(
    pairs: Iterable[tuple[str, str]],
    replacement_rows: Iterable[dict],
) -> int:

    """새 행 적재 후 교체 대상의 정확한 PK 외 stale 행만 지운다."""
    replacements = sorted({(str(cik), str(accession_no)) for cik, accession_no in pairs})
    if not replacements:
        return 0

    replacement_set = set(replacements)
    keep_keys = {
        _metric_key(row)
        for row in replacement_rows
        if (str(row["cik"]), str(row["accession_no"])) in replacement_set
    }
    deleted = 0
    for start in range(0, len(replacements), _DELETE_ACCESSION_BATCH):
        chunk = replacements[start : start + _DELETE_ACCESSION_BATCH]
        chunk_set = set(chunk)
        existing = select_all_paged(
            lambda chunk=chunk: sb.schema(_SCHEMA).table(_METRICS_TABLE)
            .select(",".join(_KEY_FIELDS))
            .in_("cik", sorted({cik for cik, _ in chunk}))
            .in_("accession_no", sorted({accession for _, accession in chunk})),
            order_by="cik,accession_no,fiscal_year,fiscal_period,segment_hash",
        )
        for row in existing:
            key = _metric_key(row)
            if key in keep_keys or (key[0], key[1]) not in chunk_set:
                continue
            response = (
                sb.schema(_SCHEMA).table(_METRICS_TABLE)
                .delete(count="exact", returning="minimal")
                .eq("cik", key[0]).eq("accession_no", key[1])
                .eq("fiscal_year", key[2]).eq("fiscal_period", key[3])
                .eq("segment_hash", key[4]).execute()
            )
            deleted += int(response.count or 0)
    log.info(
        "segments stale metrics cleanup: %d행 (%d개 공시, keep=%d)",
        deleted,
        len(replacements),
        len(keep_keys),
    )
    return deleted


def delete_history_before(cutoff: str) -> dict[str, int]:
    """보존 하한 이전의 지표와 공시 상태를 외래키 순서대로 제거한다.

    ``segment_metrics``가 ``filings``를 참조하므로 자식 지표를 먼저 지운다. 각
    DELETE는 독립 트랜잭션이지만 이 순서에서는 중간 실패가 참조 무결성을 깨지
    않으며, 다음 실행이 남은 부모 행을 멱등하게 정리한다.
    """
    metrics = (
        sb.schema(_SCHEMA)
        .table(_METRICS_TABLE)
        .delete(count="exact", returning="minimal")
        .lt("period_end", cutoff)
        .execute()
    )
    accessions = select_all_paged(
        lambda: sb.schema(_SCHEMA).table(_FILINGS_TABLE)
        .select("accession_no").lt("report_date", cutoff),
        order_by="accession_no",
    )
    accession_values = [str(row["accession_no"]) for row in accessions]
    processing_deleted = 0
    for chunk in chunk_filter_values(accession_values, _DELETE_ACCESSION_BATCH):
        response = (
            sb.schema(_SCHEMA).table(_PROCESSING_TABLE)
            .delete(count="exact", returning="minimal")
            .eq("content_type", CONTENT_SEGMENTS)
            .in_("accession_no", chunk).execute()
        )
        processing_deleted += int(response.count or 0)
    deleted = {
        "metrics_deleted": metrics.count or 0,
        "processing_deleted": processing_deleted,
    }
    log.info("segments history deleted before=%s counts=%s", cutoff, deleted)
    return deleted


def ciks_missing_segments(period_kind: str | None = None) -> set[str]:
    """해당 기간 종류의 핵심 세그먼트 지표가 없는 추적 회사를 반환한다."""
    tracked = tracked_ciks()
    if not tracked:
        return set()
    rows = select_paged_in_chunks(
        lambda chunk: sb.schema(_SCHEMA).table(_METRICS_TABLE)
        .select("cik,fiscal_period").in_("cik", chunk),
        sorted(tracked),
        order_by="cik,fiscal_period",
        paged_reader=select_all_paged,
    )
    wanted_periods = (
        {"FY"} if period_kind == "annual"
        else {"Q1", "Q2", "Q3", "Q4"} if period_kind == "quarter"
        else {str(period_kind)} if period_kind else None
    )
    present = {
        str(row["cik"])
        for row in rows
        if wanted_periods is None or str(row.get("fiscal_period")) in wanted_periods
    }
    return tracked - present


def _upsert_chunked(table: str, rows: list[dict], conflict: str) -> int:
    n = 0
    for i in range(0, len(rows), _UPSERT_BATCH):
        chunk = rows[i : i + _UPSERT_BATCH]
        sb.schema(_SCHEMA).table(table).upsert(chunk, on_conflict=conflict).execute()
        n += len(chunk)
    return n


def upsert_filings(rows: list[dict]) -> int:
    if not rows:
        return 0
    if any(not row.get("cik") or "ticker" in row for row in rows):
        raise ValueError("segment filing rows must be keyed only by cik")
    deduped = _dedupe(rows, ("cik", "accession_no"))
    filings = [
        {
            "accession_no": row["accession_no"],
            "cik": str(row["cik"]).zfill(10),
            "form_type": row["form_type"],
            "filing_date": row.get("filing_date") or row.get("accepted_date"),
            "report_date": row.get("report_date"),
            "source": row.get("source") or "sec_edgar",
        }
        for row in deduped
        if row.get("accession_no") and (row.get("filing_date") or row.get("accepted_date"))
    ]
    if len(filings) != len(deduped):
        raise ValueError("segment filing rows require accession_no, cik, form_type, and filing_date")
    _upsert_chunked(_FILINGS_TABLE, filings, "accession_no")
    processing = [
        {
            "accession_no": row["accession_no"],
            "content_type": CONTENT_SEGMENTS,
            "mapping_version": row.get("mapping_version") or MAPPING_VERSION,
            "status": row.get("status") or "empty",
            "facts_count": int(row.get("facts_count") or 0),
            "rows_count": int(row.get("rows_count") or 0),
            "updated_at": utc_now_iso(),
        }
        for row in deduped
    ]
    n = _upsert_chunked(
        _PROCESSING_TABLE,
        processing,
        "accession_no,content_type,mapping_version",
    )
    log.info("filings and segment processing states upserted: %d", n)
    return n


def _company_metrics_for(rows: list[dict]) -> dict[tuple[str, int, str], dict]:
    """세그먼트 지표와 대조할 회사 핵심 지표만 같은 회계기간으로 읽는다."""
    targets = {
        (str(row["cik"]), int(row["fiscal_year"]), str(row["fiscal_period"]))
        for row in rows
    }
    if not targets:
        return {}
    ciks = sorted({cik for cik, _, _ in targets})
    years = sorted({year for _, year, _ in targets})
    periods = {period for _, _, period in targets}
    annual_targets = {
        (cik, fiscal_year)
        for cik, fiscal_year, fiscal_period in targets
        if fiscal_period == "FY"
    }
    if annual_targets:
        periods.update(_QUARTER_PERIODS)
    fetched = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
        .select(
            "cik,fiscal_year,fiscal_period,revenue,gross_profit,"
            "operating_income_loss,pretax_income_loss,net_income,assets"
        )
        .in_("cik", chunk)
        .in_("fiscal_year", years)
        .in_("fiscal_period", sorted(periods)),
        ciks,
        order_by="cik,fiscal_year,fiscal_period",
        paged_reader=select_all_paged,
    )
    out: dict[tuple[str, int, str], dict] = {}
    quarters: dict[tuple[str, int], dict[str, dict]] = {}
    for row in fetched:
        key = (str(row["cik"]), int(row["fiscal_year"]), str(row["fiscal_period"]))
        values = {
            column: value
            for column, value in row.items()
            if column not in {"cik", "fiscal_year", "fiscal_period"}
            and value is not None
        }
        if key in targets:
            out[key] = values
        if key[:2] in annual_targets:
            quarters.setdefault(key[:2], {})[key[2]] = values

    for cik, fiscal_year, fiscal_period in targets:
        if fiscal_period != "FY" or (cik, fiscal_year, fiscal_period) in out:
            continue
        annual_quarters = quarters.get((cik, fiscal_year), {})
        if not all(period in annual_quarters for period in _QUARTER_PERIODS):
            continue
        annual = {
            column: sum(
                float(annual_quarters[period][column])
                for period in _QUARTER_PERIODS
            )
            for column in _ANNUAL_FLOW_BASELINE_COLUMNS
            if all(
                annual_quarters[period].get(column) is not None
                for period in _QUARTER_PERIODS
            )
        }
        q4_assets = annual_quarters["Q4"].get("assets")
        if q4_assets is not None:
            annual["assets"] = q4_assets
        if annual:
            out[(cik, fiscal_year, fiscal_period)] = annual
    return out


def _compact_row(row: dict) -> dict | None:
    """품질 검증을 통과한 핵심 값만 영구 저장 형태로 투영한다."""
    if str(row.get("segment_type")) not in _SEGMENT_TYPES:
        return None
    dimension_count = int(row.get("dimension_count") or 0)
    if dimension_count not in (1, 2):
        return None
    if dimension_count == 2 and not (row.get("secondary_axis") and row.get("secondary_member")):
        return None

    revenue_ok = str(row.get("quality_status")) in _USABLE_QUALITY
    profit_ok = (
        str(row.get("profit_quality_status")) in _USABLE_QUALITY
        and bool(row.get("profit_measure_kind"))
    )
    assets_ok = str(row.get("assets_quality_status")) in _USABLE_QUALITY
    revenue = row.get("revenue") if revenue_ok else None
    profit = row.get("profit_loss") if profit_ok else None
    assets = row.get("assets") if assets_ok else None
    if revenue is None and profit is None and assets is None:
        return None

    secondary_axis = row.get("secondary_axis") if dimension_count == 2 else None
    secondary_member = row.get("secondary_member") if dimension_count == 2 else None
    return {
        "cik": row["cik"],
        "fiscal_year": row["fiscal_year"],
        "fiscal_period": row["fiscal_period"],
        "period_end": row["period_end"],
        "accession_no": row["accession_no"],
        "segment_hash": row["segment_hash"],
        "segment_type": row["segment_type"],
        "axis": row["axis"],
        "member": row["member"],
        # 2차원 여부는 이 두 컬럼의 존재로만 나타낸다(별도 depth 컬럼 없음).
        "secondary_axis": secondary_axis,
        "secondary_member": secondary_member,
        "is_derived": bool(row.get("is_derived")),
        "revenue": revenue,
        "quality_status": row.get("quality_status") if revenue is not None else None,
        # 커버리지는 1차원 분할의 성질이다.
        "coverage_ratio": (
            row.get("coverage_ratio")
            if revenue is not None and secondary_axis is None else None
        ),
        "profit_loss": profit,
        "profit_measure_kind": row.get("profit_measure_kind") if profit is not None else None,
        "profit_quality_status": (
            row.get("profit_quality_status") if profit is not None else None
        ),
        "assets": assets,
        "assets_quality_status": (
            row.get("assets_quality_status") if assets is not None else None
        ),
    }


def compact_rows(rows: list[dict]) -> list[dict]:
    """검증된 단일축 핵심 지표만 남기고 원본·설명용 메타데이터를 버린다."""
    return [compact for row in rows if (compact := _compact_row(row))]


def upsert_segment_metrics_with_rows(rows: list[dict]) -> tuple[int, list[dict]]:
    """압축 저장하고 실제로 영속화한 정확한 행 집합도 함께 반환한다."""
    if not rows:
        return 0, []
    if any(not row.get("cik") or "ticker" in row for row in rows):
        raise ValueError("segment metric rows must be keyed only by cik")
    deduped = _dedupe(rows, _KEY_FIELDS)
    assessed = assess_rows(deduped, _company_metrics_for(deduped))
    compacted = compact_rows(assessed)
    n = _upsert_chunked(_METRICS_TABLE, compacted, _METRICS_CONFLICT)
    log.info("segment_metrics upserted: %d/%d", n, len(assessed))
    return n, compacted


def upsert_segment_metrics(rows: list[dict]) -> int:
    """회사 재무와 대조한 뒤 핵심 매출·이익·자산만 압축 저장한다."""
    return upsert_segment_metrics_with_rows(rows)[0]


def _hydrate_quality_inputs(row: dict) -> dict:
    """압축 행을 파생 계산 품질 재평가에 필요한 메모리 형태로 복원한다.

    분류·추출 경로(classification_method, *_method)는 저장하지 않는다. 등급을 정할 때
    쓰는 입력이고, 그 결과인 등급 자체가 `*_quality_status`로 남기 때문이다. 저장된
    행은 정의상 그 게이트를 이미 통과한 것뿐이므로(통과하지 못하면 `_compact_row`가
    버린다), 재평가가 **저장된 등급을 그대로 재현하도록** 입력을 맞춰 준다. 그러지
    않으면 Q4 파생 행이 부모보다 좋거나 나쁜 등급을 받는다.
    """
    def _method_for(status: object) -> str:
        return "candidate" if status == "partial" else "edgartools"

    out = dict(row)
    out["dimension_count"] = 1 if not row.get("secondary_axis") else 2
    out["classification_method"] = (
        "heuristic" if row.get("quality_status") == "partial" else "standard"
    )
    out["concept_method"] = _method_for(row.get("quality_status"))
    out["metric_methods"] = {
        "revenue": _method_for(row.get("quality_status")),
        "profit_loss": _method_for(row.get("profit_quality_status")),
        "assets": _method_for(row.get("assets_quality_status")),
    }
    return out


def hydrate_metric_rows(rows: Iterable[dict]) -> list[dict]:
    """이미 압축된 행을 파생 계산 입력 형태로 복원한다."""
    return [_hydrate_quality_inputs(row) for row in rows]


def fetch_metric_years(pairs: set[tuple[str, int]]) -> list[dict]:
    """여러 CIK/year의 파생 계산 입력을 압축 테이블에서 읽는다."""
    if not pairs:
        return []

    rows: list[dict] = []
    years = sorted({year for _, year in pairs})
    for year in years:
        ciks = sorted(cik for cik, pair_year in pairs if pair_year == year)
        for idx in range(0, len(ciks), 100):
            chunk = ciks[idx : idx + 100]
            rows.extend(
                select_all_paged(
                    lambda chunk=chunk, year=year: sb.schema(_SCHEMA)
                    .table(_METRICS_TABLE)
                    .select("*")
                    .eq("fiscal_year", year)
                    .in_("cik", chunk)
                    .order("cik").order("fiscal_period").order("segment_hash"),
                    order_by='cik,fiscal_period,segment_hash',
                )
            )
    return [
        _hydrate_quality_inputs(row)
        for row in rows
        if (str(row["cik"]), int(row["fiscal_year"])) in pairs
    ]


def _period_parts(period_key: str) -> tuple[int | None, str | None]:
    try:
        return int(period_key[:4]), period_key[4:]
    except (TypeError, ValueError):
        return None, None


FILING_CONTENT_SEGMENTS = "segments"


#: 스냅샷이 읽는 지표 컬럼. 두 경로가 같은 목록을 봐야 한 종목을 따로 물었을
#: 때와 묶어서 물었을 때가 달라지지 않는다.
_SNAPSHOT_METRIC_COLUMNS = (
    "cik,fiscal_year,fiscal_period,period_end,accession_no,segment_type,"
    "axis,member,secondary_axis,secondary_member,"
    "revenue,quality_status,coverage_ratio,"
    "profit_loss,profit_quality_status,assets,assets_quality_status"
)

#: 스냅샷 하나에 담는 공시 수와 지표 행 수. 두 경로가 같은 값을 써야 한 종목을
#: 따로 물었을 때와 묶어서 물었을 때가 달라지지 않는다.
_SNAPSHOT_FILINGS = 2
_SNAPSHOT_METRICS = 20


class _reverse_text:
    """`reverse=True` 정렬 안에서 문자열만 오름차순으로 되돌린다."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _reverse_text) and self.value == other.value

    def __lt__(self, other: "_reverse_text") -> bool:
        return self.value > other.value


def _select_snapshot(ticker: str, filings: list[dict], metrics: list[dict]) -> dict:
    """한 종목의 공시·지표를 스냅샷 선택 규칙으로 줄인다."""
    chosen = sorted(
        filings,
        key=lambda row: (str(row.get("filing_date") or ""), str(row["accession_no"])),
        reverse=True,
    )[:_SNAPSHOT_FILINGS]
    if not chosen:
        return {"filings": [], "metrics": []}
    accessions = {str(row["accession_no"]) for row in chosen}
    rows = [
        {**row, "ticker": str(ticker).upper()}
        for row in metrics if str(row.get("accession_no")) in accessions
    ]
    # 매출이 없는 행은 서로 동점이다. 순서를 매출 하나로만 정하면 상위 N개를
    # 자르는 자리에서 **조회 순서가 결과를 정한다** — 같은 종목을 따로 물었을
    # 때와 묶어서 물었을 때 카드에 다른 세그먼트가 실렸다. 동점은 이름으로 가른다.
    rows.sort(key=lambda row: (
        row.get("revenue") is not None,
        row.get("revenue") or 0,
        _reverse_text(str(row.get("accession_no") or "")),
        _reverse_text(str(row.get("axis") or "")),
        _reverse_text(str(row.get("member") or "")),
        _reverse_text(str(row.get("secondary_member") or "")),
    ), reverse=True)
    return {"filings": chosen, "metrics": rows[:_SNAPSHOT_METRICS]}


def segment_snapshots_as_of(tickers: Sequence[str], as_of_at: datetime) -> dict[str, dict]:
    """여러 종목의 세그먼트 스냅샷을 한 번에 읽는다.

    종목마다 `segment_snapshot_as_of`를 부르면 종목당 왕복이 네 번 이상이다
    (증권→공시→처리상태→지표). 실측 63초가 여기였다.
    """
    if as_of_at.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    symbols = sorted({str(value).upper() for value in tickers})
    if not symbols:
        return {}
    cutoff_date = as_of_at.astimezone(timezone.utc).date().isoformat()
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
        return {}
    filing_rows = [
        row for row in select_paged_in_chunks(
            lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(_FILINGS_TABLE)
            .select("accession_no,cik,form_type,report_date,filing_date").in_("cik", chunk),
            sorted(tickers_by_cik), order_by="cik,filing_date,accession_no",
            paged_reader=select_all_paged,
        )
        if str(row.get("filing_date") or "") <= cutoff_date
    ]
    processing = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(_PROCESSING_TABLE)
        .select("accession_no,status,updated_at")
        .eq("content_type", FILING_CONTENT_SEGMENTS)
        .eq("mapping_version", MAPPING_VERSION)
        .eq("status", "parsed")
        .lte("updated_at", as_of_at.astimezone(timezone.utc).isoformat())
        .in_("accession_no", chunk),
        sorted({str(row["accession_no"]) for row in filing_rows}),
        order_by="accession_no", paged_reader=select_all_paged,
    ) if filing_rows else []
    updated_by_accession = {str(row["accession_no"]): row.get("updated_at") for row in processing}
    parsed_by_cik: dict[str, list[dict]] = defaultdict(list)
    for row in filing_rows:
        key = str(row["accession_no"])
        if key in updated_by_accession:
            parsed_by_cik[str(row["cik"]).zfill(10)].append(
                {**row, "status": "parsed", "updated_at": updated_by_accession[key]}
            )
    # 지표는 실제로 고른 공시만 읽는다 — 공시 전체를 읽으면 창이 통째로 온다.
    wanted: set[str] = set()
    chosen_by_ticker: dict[str, list[dict]] = {}
    for cik, rows in parsed_by_cik.items():
        for ticker in tickers_by_cik[cik]:
            chosen = sorted(
                rows,
                key=lambda row: (str(row.get("filing_date") or ""), str(row["accession_no"])),
                reverse=True,
            )[:_SNAPSHOT_FILINGS]
            chosen_by_ticker[ticker] = [{**row, "ticker": ticker} for row in chosen]
            wanted.update(str(row["accession_no"]) for row in chosen)
    metrics = select_paged_in_chunks(
        lambda chunk: sb.schema(SCHEMA_FUNDAMENTALS).table(_METRICS_TABLE)
        .select(_SNAPSHOT_METRIC_COLUMNS).in_("accession_no", chunk),
        sorted(wanted), order_by="accession_no,fiscal_year,fiscal_period",
        paged_reader=select_all_paged,
    ) if wanted else []
    return {
        ticker: _select_snapshot(ticker, filings, metrics)
        for ticker, filings in chosen_by_ticker.items()
    }


def segment_snapshot_as_of(ticker: str, as_of_at: datetime) -> dict:
    """cutoff 이전에 파싱이 끝난 최근 공시 2건과 그 차원 지표."""
    if as_of_at.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    cutoff_date = as_of_at.astimezone(timezone.utc).date().isoformat()
    securities = select_all_paged(
        lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("ticker,cik").eq("ticker", ticker),
        order_by="ticker",
    )
    if not securities or not securities[0].get("cik"):
        return {"filings": [], "metrics": []}
    cik = str(securities[0]["cik"]).zfill(10)
    filing_rows = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(_FILINGS_TABLE)
        .select("accession_no,cik,form_type,report_date,filing_date")
        .eq("cik", cik),
        order_by="filing_date,accession_no",
    )
    filing_rows = [
        row for row in filing_rows
        if str(row.get("filing_date") or "") <= cutoff_date
    ]
    candidate_accessions = [str(row["accession_no"]) for row in filing_rows]
    processing: list[dict] = []
    for start in range(0, len(candidate_accessions), 100):
        chunk = candidate_accessions[start : start + 100]
        processing.extend(
            select_all_paged(
                lambda chunk=chunk: sb.schema(SCHEMA_FUNDAMENTALS)
                .table(_PROCESSING_TABLE)
                .select("accession_no,status,updated_at")
                .eq("content_type", FILING_CONTENT_SEGMENTS)
                .eq("mapping_version", MAPPING_VERSION)
                .eq("status", "parsed")
                .lte("updated_at", as_of_at.astimezone(timezone.utc).isoformat())
                .in_("accession_no", chunk),
                order_by="accession_no",
            )
        )
    parsed_accessions = {str(row["accession_no"]) for row in processing}
    updated_by_accession = {str(row["accession_no"]): row.get("updated_at") for row in processing}
    filings = [
        {
            **row,
            "ticker": str(ticker).upper(),
            "status": "parsed",
            "updated_at": updated_by_accession.get(str(row["accession_no"])),
        }
        for row in filing_rows
        if str(row["accession_no"]) in parsed_accessions
    ]
    chosen = sorted(
        filings,
        key=lambda row: (str(row.get("filing_date") or ""), str(row["accession_no"])),
        reverse=True,
    )[:_SNAPSHOT_FILINGS]
    selected_accessions = [str(row["accession_no"]) for row in chosen]
    metrics = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(_METRICS_TABLE)
        .select(_SNAPSHOT_METRIC_COLUMNS).in_("accession_no", selected_accessions),
        order_by="accession_no,fiscal_year,fiscal_period",
    ) if selected_accessions else []
    return _select_snapshot(ticker, filings, metrics)
