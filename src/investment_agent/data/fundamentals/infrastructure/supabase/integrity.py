"""정합성 점검이 읽는 조회와 이슈 기록."""
from __future__ import annotations

from datetime import date

from investment_agent.platform.clock import us_market_today
from investment_agent.platform.logging import get_logger
from investment_agent.platform.db.postgres import sb, select_all_paged, select_paged_in_chunks
from investment_agent.data.fundamentals.domain.taxonomy import gaap_concepts, segment_axes
from investment_agent.data.fundamentals.domain.taxonomy.financial_columns import (
    CORE_COLUMNS,
    PERSISTED_METADATA_COLUMNS,
)

# --- DB 식별자 (SSOT) ---------------------------------------------------
SCHEMA_FUNDAMENTALS = "fundamentals"
SCHEMA_UNIVERSE = "universe"
T_FINANCIALS = "financials"
T_FILINGS = "filings"
T_SEGMENT_METRICS = "segment_metrics"
T_FILING_PROCESSING = "filing_processing"
T_EARNINGS_SCHEDULE = "earnings_schedule_versions"
T_SECURITIES = "securities"
# ----------------------------------------------------------------------

log = get_logger(__name__)

PIPELINE = "fundamentals"

# 관측된 정상 범위의 하한. 이 밑으로 떨어지면 매핑이나 원천이 깨진 것이다.
# 2026-08-26 전수 재적재 실측: eps 90.9 · 배당 69.2 · SG&A 75.5 · goodwill 85.4.
FILL_FLOORS: dict[str, float] = {
    "revenue": 85.0,
    "assets": 95.0,
    "liabilities": 95.0,
    "net_income": 90.0,
    "eps_diluted_gaap": 70.0,
    "common_dividends_paid": 50.0,
    "net_cash_from_operating_activities": 85.0,
    "capital_expenses": 70.0,
    "selling_general_and_admin_expenses": 60.0,
}


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _db_columns() -> set[str]:
    """PostgREST가 노출하는 canonical financials 컬럼 집합.

    한 행만 읽어 키를 본다. information_schema는 Data API로 못 읽는다.
    """
    rows = (
        sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
        .select("*").limit(1).execute().data or []
    )
    return set(rows[0]) if rows else set()


def collect_integrity_facts() -> dict:
    """판정에 필요한 숫자만 모은다. 등급 매기기는 use case가 한다."""
    db_columns = _db_columns()
    code_columns = set(CORE_COLUMNS) | set(PERSISTED_METADATA_COLUMNS)

    newest_filing = (
        sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILINGS)
        .select("filing_date").order("filing_date", desc=True).limit(1).execute().data or []
    )
    mv_latest = (
        sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
        .select("period_end").order("period_end", desc=True).limit(1).execute().data or []
    )
    total = (
        sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
        .select("cik", count="exact").limit(1).execute().count or 0
    )
    current_mapping_rows = (
        sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
        .select("cik", count="exact")
        .eq("mapping_version", gaap_concepts.SEMANTIC_POLICY_VERSION)
        .limit(1).execute().count or 0
    )
    securities = select_all_paged(
        lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
        .select("security_id,ticker,cik").eq("is_tracked", True).not_.is_("cik", "null"),
        order_by="ticker",
    )
    financial_ciks = {
        str(row["cik"]).zfill(10)
        for row in select_all_paged(
            lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
            .select("cik"), order_by="cik"
        )
        if row.get("cik")
    }
    missing_financial_tickers = sorted(
        str(row["ticker"]) for row in securities
        if str(row.get("cik") or "").zfill(10) not in financial_ciks
    )

    fill_rates: dict[str, float] = {}
    for column in FILL_FLOORS:
        if column not in db_columns:
            continue
        filled = (
            sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
            .select("cik", count="exact").not_.is_(column, "null")
            .limit(1).execute().count or 0
        )
        fill_rates[column] = (100.0 * filled / total) if total else 0.0

    derived_liability_rows = 0
    if "is_liabilities_derived" in db_columns:
        derived_liability_rows = (
            sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
            .select("cik", count="exact")
            .eq("is_liabilities_derived", True)
            .limit(1).execute().count or 0
        )

    unknown_equity_scope_rows = 0
    if "common_equity_scope" in db_columns:
        unknown_equity_scope_rows = (
            sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
            .select("cik", count="exact")
            .not_.is_("common_equity", "null")
            .eq("common_equity_scope", "unknown")
            .limit(1).execute().count or 0
        )

    financial_rows = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FINANCIALS)
        .select("cik,source_accession_no,period_end,fiscal_year,fiscal_period,assets,liabilities,common_equity,"
                "minority_interest_balance,mezzanine_equity,preferred_stock,"
                "common_equity_scope,is_liabilities_derived,mapping_version"),
        order_by="cik,period_end,source_accession_no",
    )
    checkable = mismatch = 0
    periods_by_cik_year: dict[tuple[str, int], set[str]] = {}
    period_ends_by_cik_period: dict[tuple[str, int, str], set[str]] = {}
    for item in financial_rows:
        key = (str(item.get("cik")), int(item["fiscal_year"]))
        periods_by_cik_year.setdefault(key, set()).add(str(item["fiscal_period"]))
        period_ends_by_cik_period.setdefault(
            (key[0], key[1], str(item["fiscal_period"])), set()
        ).add(str(item["period_end"]))
        values = [item.get(name) for name in ("assets", "liabilities", "common_equity")]
        if all(value is not None for value in values):
            checkable += 1
            rhs = sum(float(item.get(name) or 0) for name in (
                "liabilities", "common_equity", "minority_interest_balance",
                "mezzanine_equity", "preferred_stock",
            ))
            if abs(float(item["assets"]) - rhs) > max(abs(float(item["assets"])) * 0.01, 1.0):
                mismatch += 1
    non_monotonic = 0
    for (cik, fiscal_year), periods in periods_by_cik_year.items():
        quarter_ends = {
            period: sorted(period_ends_by_cik_period.get((cik, fiscal_year, period), set()))
            for period in ("Q1", "Q2", "Q3", "Q4")
            if period in periods
        }
        present = [period for period in ("Q1", "Q2", "Q3", "Q4") if period in quarter_ends]
        if len(present) < 2:
            continue
        if any(
            max(quarter_ends[earlier]) > min(quarter_ends[later])
            for earlier, later in zip(present, present[1:])
        ):
            non_monotonic += 1
    duplicate_period_end = sum(
        max(len(period_ends) - 1, 0)
        for period_ends in period_ends_by_cik_period.values()
    )
    fiscal_sequence = {
        "non_monotonic_rows": non_monotonic,
        "duplicate_period_end_rows": duplicate_period_end,
    }

    segment_rows = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_SEGMENT_METRICS)
        .select("cik,accession_no,fiscal_year,fiscal_period,period_end,segment_hash,"
                "segment_type,axis,member,secondary_axis,secondary_member,"
                "revenue,quality_status,coverage_ratio,profit_loss,"
                "profit_quality_status,profit_measure_kind,assets,assets_quality_status"),
        order_by="cik,accession_no,fiscal_year,fiscal_period,segment_hash",
    )
    processing_rows = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_FILING_PROCESSING)
        .select("accession_no,content_type,mapping_version,status"),
        order_by="accession_no,content_type,mapping_version",
    )
    segment_accessions = {str(row["accession_no"]) for row in segment_rows}
    segment_processing = {
        str(row["accession_no"]): row for row in processing_rows
        if row.get("content_type") == "segments"
        and row.get("mapping_version") == segment_axes.SEGMENT_MAPPING_VERSION
    }
    segment_integrity = {
        "metric_rows": len(segment_rows),
        "filing_rows": len(segment_processing),
        "stale_mapping_filing_rows": sum(
            1 for row in processing_rows
            if row.get("content_type") == "segments"
            and row.get("mapping_version") != segment_axes.SEGMENT_MAPPING_VERSION
        ),
        "tracked_without_filing_rows": sum(
            1 for row in securities
            if str(row.get("cik") or "").zfill(10)
            not in {str(metric.get("cik")) for metric in segment_rows}
        ),
        "orphan_metric_rows": sum(
            1 for accession in segment_accessions if accession not in segment_processing
        ),
        "nonparsed_metric_state_rows": sum(
            1 for accession in segment_accessions
            if segment_processing.get(accession, {}).get("status") != "parsed"
        ),
    }

    # 종목별 최신 스냅샷만 센다. 예정일은 자주 바뀌어 관측마다 행이 쌓이므로,
    # 전체를 세면 이미 superseded 상태인 관측까지 미분류로 잡혀 비율이 부풀려진다.
    rows = select_all_paged(
        lambda: sb.schema(SCHEMA_FUNDAMENTALS).table(T_EARNINGS_SCHEDULE)
        .select("security_id,snapshot_date,expected_report_date,expected_session")
        .gte("expected_report_date", us_market_today().isoformat()),
        order_by="security_id,snapshot_date",
    )
    newest_by_ticker: dict[str, dict] = {}
    security_ids = {int(row["security_id"]) for row in rows if row.get("security_id") is not None}
    ticker_by_id = {
        int(row["security_id"]): str(row["ticker"])
        for row in securities if row.get("security_id") is not None
    }
    if security_ids:
        security_rows = select_paged_in_chunks(
            lambda chunk: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
            .select("security_id,ticker").in_("security_id", chunk),
            sorted(security_ids),
            order_by="security_id",
            paged_reader=select_all_paged,
        )
        ticker_by_id.update({int(row["security_id"]): str(row["ticker"]) for row in security_rows})
    for row in rows:
        ticker = ticker_by_id.get(int(row["security_id"]))
        if not ticker:
            continue
        current = newest_by_ticker.get(ticker)
        if current is None or str(row["snapshot_date"]) > str(current["snapshot_date"]):
            newest_by_ticker[ticker] = {**row, "ticker": ticker}
    schedules = list(newest_by_ticker.values())
    unknown = sum(1 for row in schedules if str(row.get("expected_session")) == "unknown")

    return {
        "columns_missing_in_db": sorted(code_columns - db_columns) if db_columns else [],
        "columns_missing_in_code": sorted(
            {
                c for c in db_columns
                if c in FILL_FLOORS
                or c.endswith(("_gaap", "_is_derived"))
            } - code_columns
        ),
        "last_filed_at": _as_date(newest_filing[0]["filing_date"]) if newest_filing else None,
        "latest_financial_period_end": _as_date(mv_latest[0]["period_end"]) if mv_latest else None,
        "row_count": total,
        "current_mapping_version": gaap_concepts.SEMANTIC_POLICY_VERSION,
        "stale_mapping_rows": max(total - current_mapping_rows, 0),
        "missing_financial_tickers": missing_financial_tickers,
        "balance_checkable_rows": checkable,
        "balance_mismatch_rows": mismatch,
        "fiscal_sequence": fiscal_sequence,
        "fill_rates": fill_rates,
        "fill_floors": FILL_FLOORS,
        "derived_liability_rows": derived_liability_rows,
        "unknown_equity_scope_rows": unknown_equity_scope_rows,
        "segment_integrity": segment_integrity,
        "schedule_rows": len(schedules),
        "schedule_unknown_session": unknown,
    }


