"""Discord-Twin 대시보드의 Supabase SELECT 전용 데이터 계층.

이 모듈은 실제 SQL 스키마에 존재하는 컬럼만 명시적으로 조회한다. 대시보드가
가져온 행을 화면에서 계산할 수는 있지만, 이 경계에서는 어떤 상태도 저장하지 않는다.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping, Sequence
from itertools import product
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from investment_agent.reporting.services.fundamental_segments import enrich_segment_rows
from investment_agent.platform.cache import cache_data
from investment_agent.reporting.models import (
    DataResult,
    normalize_observed_at,
    public_exception_message,
)
from investment_agent.reporting.services.investment import build_decision_cases_read_model
from investment_agent.reporting.readers.runtime import read_local_rows, read_runtime_rows
from investment_agent.reporting.readers.research import (
    load_local_features,
    load_local_research_records,
    load_local_strategy_data,
)

DB_SOURCE = "DB 저장 데이터 · v1 Supabase"
MACRO_KPI_SERIES: tuple[str, ...] = ("FEAR_GREED", "TNX", "DXY", "WTI", "VIX")
PRICE_PERIOD_DAYS = {
    "1mo": 31,
    "3mo": 93,
    "6mo": 186,
    "1y": 366,
    "2y": 731,
    "5y": 1_826,
    "10y": 3_653,
    "max": None,
}

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

# --- fundamentals DB 식별자 (SSOT) --------------------------------------
SCHEMA_FUNDAMENTALS = "fundamentals"
SCHEMA_INSTITUTIONAL = "institutional"
SCHEMA_MARKET = "market"
SCHEMA_UNIVERSE = "universe"
SCHEMA_REPORTING = "reporting"
T_FINANCIALS = "financials"
T_FILINGS = "filings"
T_FILING_PROCESSING = "filing_processing"
T_EARNINGS_ESTIMATES = "earnings_estimates"
T_SHARE_CLASS_SNAPSHOTS = "share_class_snapshots"
T_SEGMENT_METRICS = "segment_metrics"
T_ENTITIES = "entities"
T_PRICES_DAILY = "prices_daily"
T_SPLIT_EVENTS = "split_events"
V_EARNINGS_SURPRISE = "earnings_surprise"
T_INSTITUTIONAL_FILINGS = "filings"
T_INSTITUTIONAL_POSITIONS = "positions"
T_SECURITY_IDENTIFIERS = "security_identifiers"
T_SECURITIES = "securities"

FILING_CONTENT_COMPANY = "company"
FILING_CONTENT_SEGMENTS = "segments"
CONSENSUS_KIND_OBSERVED = "observed"


def _membership_chunks(
    filters: Mapping[str, Sequence[Any]],
) -> Iterator[dict[str, Sequence[Any]]]:
    """`in` 목록을 URL 한도 안에 들어가는 조각들의 조합으로 나눈다.

    조각 크기는 platform이 정한 것 하나를 쓴다 — 여기서 따로 정하면 두 경계가
    서로 다른 한도를 주장하게 된다.
    """
    from investment_agent.platform.db.postgres import IN_FILTER_CHUNK

    columns = list(filters)
    pieces = [
        [tuple(values[at:at + IN_FILTER_CHUNK]) for at in range(0, len(values), IN_FILTER_CHUNK)]
        for values in (filters[column] for column in columns)
    ]
    for combination in product(*pieces) if columns else [()]:
        yield dict(zip(columns, combination))


def _display_security_profile(row: Mapping[str, Any]) -> dict[str, Any]:
    """entity·security 행을 대시보드 표시 계약으로 투영한다."""
    value = dict(row)
    value.update({
        "name": row.get("company_name") or row.get("ticker"),
        "name_ko": row.get("company_name_ko"),
        "exchange": row.get("exchange_code"),
        "sic_industry": row.get("sic_industry_name"),
        "sic_division": row.get("sic_division_name"),
    })
    return value


def _attach_entity_profiles(gateway: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """security의 CIK로 entity metadata를 붙여 화면용 평면 행을 만든다."""
    ciks = sorted({str(row["cik"]) for row in rows if row.get("cik")})
    if not ciks:
        return rows
    entities = gateway.select_rows(
        schema=SCHEMA_UNIVERSE,
        table=T_ENTITIES,
        columns=(
            "cik,company_name,company_name_ko,entity_type,sic_code,sic_industry_name,"
            "sic_division_name,fiscal_year_end,state_of_incorporation,former_names"
        ),
        in_values={"cik": ciks},
        order=(("cik", False),),
        page_size=1_000,
        max_rows=20_000,
    )
    by_cik = {str(row["cik"]): row for row in entities}
    merged: list[dict[str, Any]] = []
    for security in rows:
        value = dict(security)
        value.update(by_cik.get(str(security.get("cik")), {}))
        merged.append(value)
    return merged

# 기업 전체 재무 wide 컬럼. 업종 특수 계정(은행·금융)이 이 표로 흡수돼 함께 온다.
_FINANCIAL_COLUMNS = (
    "cik,fiscal_year,fiscal_period,source_accession_no,source_filing_date,period_end,"
    "revenue,cost_of_goods_and_services_sold,gross_profit,"
    "research_and_development_expenses,selling_general_and_admin_expenses,"
    "operating_income_loss,interest_expense,"
    "pretax_income_loss,income_taxes,net_income,minority_interest_income,"
    "net_income_to_common_shareholders,"
    "eps_basic_gaap,eps_diluted_gaap,dividends_declared_per_share,"
    "assets,current_assets_total,cash_and_cash_equivalents,short_term_investments,"
    "trade_receivables,inventories,property_plant_equipment_net,goodwill,"
    "intangible_assets_excluding_goodwill,operating_lease_right_of_use_asset,"
    "liabilities,current_liabilities_total,"
    "trade_payables,short_term_debt,current_portion_of_long_term_debt,long_term_debt,"
    "total_debt_including_current,common_equity,minority_interest_balance,"
    "preferred_stock,retained_earnings,net_cash_from_operating_activities,"
    "net_cash_from_investing_activities,net_cash_from_financing_activities,"
    "depreciation_amortization_cf,stock_based_compensation_cf,"
    "capital_expenses,acquisitions_net_of_cash,stock_repurchase_payments,"
    "common_dividends_paid,long_term_debt_issued,long_term_debt_repaid,"
    "operating_lease_current_debt_equivalent,"
    "operating_lease_non_current_debt_equivalent,shares_average,"
    "shares_fully_diluted_average,net_interest_income,provision_for_credit_losses,"
    "net_loans_and_leases,total_deposits,common_equity_scope,is_liabilities_derived,"
    "mezzanine_equity,preferred_stock,mapping_version,updated_at"
)
# 컨센서스 스냅샷 전 컬럼. 최신 관측 축약도 공시 전 결합도 이 원본에서만 나온다.
_CONSENSUS_COLUMNS = (
    "security_id,target_fiscal_year,target_fiscal_period,target_period_end,snapshot_date,"
    "snapshot_kind,source,source_horizon,eps_avg,eps_low,eps_high,eps_analysts,"
    "revenue_avg,revenue_low,revenue_high,revenue_analysts,revisions_up_7d,"
    "revisions_up_30d,revisions_down_7d,revisions_down_30d,collected_at"
)
_FILING_PROCESSING_COLUMNS = (
    "accession_no,content_type,mapping_version,status,facts_count,rows_count,updated_at"
)
# ----------------------------------------------------------------------


def _security_identity(gateway: Any, tickers: Sequence[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    """화면의 ticker를 canonical security_id/CIK로 해석한다."""
    wanted = sorted({str(ticker).upper() for ticker in tickers if str(ticker).strip()})
    if not wanted:
        return {}, {}
    rows = gateway.select_rows(
        schema=SCHEMA_UNIVERSE,
        table=T_SECURITIES,
        columns="security_id,ticker,cik",
        in_values={"ticker": wanted},
        order=(("ticker", False),),
        page_size=1_000,
        max_rows=2_000,
    )
    by_ticker = {str(row["ticker"]).upper(): row for row in rows}
    by_cik = {
        str(row["cik"]).zfill(10): row
        for row in rows if row.get("cik")
    }
    return by_ticker, by_cik


def _canonical_financial_rows(
    gateway: Any, tickers: Sequence[str], *, limit: int | None = None
) -> list[dict[str, Any]]:
    """canonical financials + filings를 dashboard 표시 행으로 투영한다."""
    by_ticker, by_cik = _security_identity(gateway, tickers)
    if not by_cik:
        return []
    rows = gateway.select_rows(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_FINANCIALS,
        columns=_FINANCIAL_COLUMNS,
        in_values={"cik": sorted(by_cik)},
        order=(("period_end", True), ("cik", False), ("source_accession_no", False)),
        page_size=1_000,
        max_rows=limit or 20_000,
    )
    accessions = sorted({str(row["source_accession_no"]) for row in rows if row.get("source_accession_no")})
    filings = gateway.select_rows(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_FILINGS,
        columns="accession_no,filing_date,report_date,form_type,available_at,source",
        in_values={"accession_no": accessions},
        order=(("filing_date", True), ("accession_no", False)),
        page_size=1_000,
        max_rows=max(len(accessions), 1),
    ) if accessions else []
    filing_by_accession = {str(row["accession_no"]): row for row in filings}
    projected: list[dict[str, Any]] = []
    for row in rows:
        security = by_cik.get(str(row.get("cik")).zfill(10))
        filing = filing_by_accession.get(str(row.get("source_accession_no")), {})
        if not security or not filing.get("filing_date"):
            continue
        projected.append({
            **row,
            "accession_no": row.get("source_accession_no"),
            "ticker": str(security["ticker"]).upper(),
            "filed_at": filing.get("filing_date"),
            "form_type": filing.get("form_type"),
            "available_at": filing.get("available_at"),
            "source": filing.get("source"),
        })
    return projected[:limit] if limit else projected


def _canonical_processing_rows(
    gateway: Any, tickers: Sequence[str], *, content_type: str
) -> list[dict[str, Any]]:
    """공시 처리 상태와 filings 사실을 화면용 ticker 행으로 결합한다."""
    _by_ticker, by_cik = _security_identity(gateway, tickers)
    if not by_cik:
        return []
    filings = gateway.select_rows(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_FILINGS,
        columns="accession_no,cik,filing_date,report_date,form_type,source",
        in_values={"cik": sorted(by_cik)},
        order=(("filing_date", True), ("accession_no", False)),
        page_size=1_000,
        max_rows=10_000,
    )
    accessions = [str(row["accession_no"]) for row in filings]
    if not accessions:
        return []
    states = gateway.select_rows(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_FILING_PROCESSING,
        columns=_FILING_PROCESSING_COLUMNS,
        equal={"content_type": content_type},
        in_values={"accession_no": accessions},
        order=(("updated_at", True), ("accession_no", False)),
        page_size=1_000,
        max_rows=10_000,
    )
    filing_by_accession = {str(row["accession_no"]): row for row in filings}
    out: list[dict[str, Any]] = []
    for state in states:
        filing = filing_by_accession.get(str(state.get("accession_no")))
        if not filing:
            continue
        security = by_cik.get(str(filing.get("cik")).zfill(10))
        if not security:
            continue
        out.append({
            **filing,
            **state,
            "ticker": str(security["ticker"]).upper(),
        })
    return out


def _canonical_segment_rows(
    gateway: Any, tickers: Sequence[str], *, limit: int = 5_000
) -> list[dict[str, Any]]:
    _by_ticker, by_cik = _security_identity(gateway, tickers)
    if not by_cik:
        return []
    rows = gateway.select_rows(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_SEGMENT_METRICS,
        columns=(
            "cik,fiscal_year,fiscal_period,period_end,accession_no,segment_hash,"
            "segment_type,axis,member,secondary_axis,secondary_member,is_derived,"
            "revenue,quality_status,coverage_ratio,profit_loss,profit_measure_kind,"
            "profit_quality_status,assets,assets_quality_status,ingested_at"
        ),
        in_values={"cik": sorted(by_cik)},
        order=(("period_end", True), ("cik", False), ("segment_type", False), ("axis", False)),
        page_size=1_000,
        max_rows=limit,
    )
    return [
        {**row, "ticker": str(by_cik[str(row["cik"]).zfill(10)]["ticker"]).upper()}
        for row in rows if str(row.get("cik")).zfill(10) in by_cik
    ]


def _canonical_price_rows(
    gateway: Any, tickers: Sequence[str], *, limit: int = 2_000
) -> list[dict[str, Any]]:
    by_ticker, _by_cik = _security_identity(gateway, tickers)
    ids = sorted({int(row["security_id"]) for row in by_ticker.values() if row.get("security_id") is not None})
    if not ids:
        return []
    rows = gateway.select_rows(
        schema=SCHEMA_MARKET,
        table=T_PRICES_DAILY,
        columns="security_id,trade_date,open,high,low,close,volume,is_repaired",
        in_values={"security_id": ids},
        order=(("trade_date", True), ("security_id", False)),
        page_size=1_000,
        max_rows=limit,
    )
    ticker_by_id = {int(row["security_id"]): str(row["ticker"]).upper() for row in by_ticker.values()}
    return [
        {**row, "ticker": ticker_by_id.get(int(row["security_id"])), "div_amount": None, "split_ratio": None}
        for row in rows if ticker_by_id.get(int(row["security_id"]))
    ]


def _price_frame(rows: list[dict[str, Any]], symbols: Sequence[str]) -> pd.DataFrame:
    """저장된 일봉 행을 기존 화면의 단일·복수 종목 DataFrame 계약으로 만든다."""

    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["Date"] = pd.to_datetime(frame["trade_date"], errors="coerce", utc=True).dt.tz_localize(None)
    frame = frame.dropna(subset=["Date", "close"])
    frame = frame.sort_values(["Date", "ticker"])
    fields = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    if len(symbols) == 1:
        result = frame.set_index("Date")[[*fields]]
        result = result.rename(columns=fields)
        result.index.name = "Date"
        return result
    wide = frame.pivot_table(index="Date", columns="ticker", values=list(fields), aggfunc="last")
    wide = wide.reindex(columns=pd.MultiIndex.from_product(
        [list(fields), list(symbols)], names=["Price", "Ticker"]
    ))
    wide.columns = pd.MultiIndex.from_tuples(
        [(fields[str(field)], str(ticker).upper()) for field, ticker in wide.columns],
        names=["Price", "Ticker"],
    )
    wide.index.name = "Date"
    return wide


@cache_data(ttl="2m", max_entries=32)
def load_price_history(tickers: str | Sequence[str], period: str = "6mo") -> DataResult:
    """저장된 ``market.prices_daily``만 읽어 가격 화면 계약으로 투영한다."""

    source = f"{DB_SOURCE} · market.prices_daily"
    values = (tickers,) if isinstance(tickers, str) else tuple(tickers)
    symbols = tuple(dict.fromkeys(str(value or "").strip().upper() for value in values if str(value or "").strip()))
    if not symbols or len(symbols) > 40 or any(not re.fullmatch(r"[A-Z0-9][A-Z0-9.^-]{0,14}", symbol) for symbol in symbols):
        return DataResult.blocked(source=source, message="유효한 종목 코드가 필요합니다.")
    selected_period = str(period or "").strip().lower()
    if selected_period not in PRICE_PERIOD_DAYS:
        return DataResult.blocked(source=source, message="허용되지 않은 가격 조회 기간입니다.")
    blocked = _preflight()
    if blocked:
        return blocked
    try:
        # 전략 재현(max)은 23개 자산의 수년치 일봉을 한 번에 읽을 수 있어야 한다.
        rows = _canonical_price_rows(_gateway(), symbols, limit=200_000)
        days = PRICE_PERIOD_DAYS[selected_period]
        if days is not None:
            start = date.today() - timedelta(days=days)
            rows = [row for row in rows if str(row.get("trade_date")) >= start.isoformat()]
        value = _price_frame(rows, symbols)
        observed_at = _latest_at(((rows, ("trade_date",)),))
        available = {str(row.get("ticker")).upper() for row in rows}
        missing = sorted(set(symbols) - available)
        if value.empty:
            return DataResult.empty(
                source=source,
                value=value,
                observed_at=observed_at,
                message="저장된 가격 관측값이 없습니다.",
            )
        return DataResult.ok(
            source=source,
            value=value,
            observed_at=observed_at,
            message=f"가격 누락 종목: {', '.join(missing)}" if missing else None,
        )
    except Exception as error:
        return DataResult.error(
            source=source,
            message=public_exception_message("저장 가격 조회에 실패했습니다.", error),
        )


def _canonical_share_rows(
    gateway: Any, tickers: Sequence[str], *, limit: int = 240
) -> list[dict[str, Any]]:
    by_ticker, _by_cik = _security_identity(gateway, tickers)
    ids = sorted({int(row["security_id"]) for row in by_ticker.values() if row.get("security_id") is not None})
    if not ids:
        return []
    rows = gateway.select_rows(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_SHARE_CLASS_SNAPSHOTS,
        columns=(
            "mapped_security_id,share_class_key,share_class_title,as_of_date,"
            "shares_outstanding,accession_no,ingested_at"
        ),
        in_values={"mapped_security_id": ids},
        order=(("as_of_date", True), ("mapped_security_id", False)),
        page_size=1_000,
        max_rows=limit,
    )
    accession_values = sorted({str(row["accession_no"]) for row in rows if row.get("accession_no")})
    filings = gateway.select_rows(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_FILINGS,
        columns="accession_no,filing_date,form_type,available_at",
        in_values={"accession_no": accession_values},
        order=(("filing_date", True), ("accession_no", False)),
        page_size=1_000,
        max_rows=max(len(accession_values), 1),
    ) if accession_values else []
    filing_by_accession = {str(row["accession_no"]): row for row in filings}
    ticker_by_id = {int(row["security_id"]): str(row["ticker"]).upper() for row in by_ticker.values()}
    return [
        {
            **row,
            "ticker": ticker_by_id.get(int(row["mapped_security_id"])),
            "shares": row.get("shares_outstanding"),
            "filed_at": filing_by_accession.get(str(row.get("accession_no")), {}).get("filing_date"),
            "available_at": filing_by_accession.get(str(row.get("accession_no")), {}).get("available_at"),
        }
        for row in rows if ticker_by_id.get(int(row["mapped_security_id"]))
    ]


class DashboardDataError(RuntimeError):
    """읽기 결과의 구조가 계약과 다를 때 사용하는 안전한 오류."""


class SelectOnlyGateway:
    """허용된 PostgREST SELECT 연산만 조합하는 좁은 게이트웨이.

    v1 관심 기업은 공개 읽기 전용인 ``universe.entities``의 관심 컬럼에서
    직접 읽는다.
    """

    #: 이름 -> 허용된 인자 이름. SQL 정의가 STABLE이고 본문이 SELECT 하나인 함수만 둔다.
    READ_ONLY_FUNCTIONS: Mapping[str, frozenset[str]] = {}

    def __init__(self, client: Any) -> None:
        from investment_agent.platform.db.postgres import SchemaClients

        self._client = client
        self._schemas = SchemaClients(client)

    @staticmethod
    def _identifier(value: str) -> str:
        current = str(value).strip()
        if not _IDENTIFIER_RE.fullmatch(current):
            raise DashboardDataError("허용되지 않은 DB 식별자입니다.")
        return current

    @classmethod
    def _columns(cls, value: str) -> str:
        columns = [item.strip() for item in str(value).split(",") if item.strip()]
        if not columns or any(not _IDENTIFIER_RE.fullmatch(item) for item in columns):
            raise DashboardDataError("명시적이고 단순한 SELECT 컬럼만 허용합니다.")
        return ",".join(columns)

    @staticmethod
    def _response_rows(response: Any) -> list[dict[str, Any]]:
        data = getattr(response, "data", None)
        if data is None:
            return []
        if not isinstance(data, list) or any(not isinstance(row, Mapping) for row in data):
            raise DashboardDataError("Supabase SELECT 응답이 행 배열이 아닙니다.")
        return [dict(row) for row in data]

    def select_rows(
        self,
        *,
        schema: str,
        table: str,
        columns: str,
        equal: Mapping[str, Any] | None = None,
        in_values: Mapping[str, Sequence[Any]] | None = None,
        order: Sequence[tuple[str, bool]] = (),
        limit: int | None = None,
        page_size: int | None = None,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        """SELECT와 허용된 필터·정렬·범위만 사용해 행을 읽는다."""

        schema_name = self._identifier(schema)
        table_name = self._identifier(table)
        selected_columns = self._columns(columns)
        equal_filters = {
            self._identifier(column): value for column, value in (equal or {}).items()
        }
        membership_filters = {
            self._identifier(column): tuple(values)
            for column, values in (in_values or {}).items()
        }
        order_fields = tuple((self._identifier(column), bool(desc)) for column, desc in order)

        if any(not values for values in membership_filters.values()):
            return []
        if limit is not None and not 1 <= int(limit) <= 20_000:
            raise DashboardDataError("SELECT limit 범위를 벗어났습니다.")
        if page_size is not None:
            if not 1 <= int(page_size) <= 1_000:
                raise DashboardDataError("SELECT page_size 범위를 벗어났습니다.")
            if not order_fields:
                raise DashboardDataError("페이지 조회에는 안정적인 정렬 컬럼이 필요합니다.")
        if max_rows is not None and not 1 <= int(max_rows) <= 200_000:
            raise DashboardDataError("SELECT max_rows 범위를 벗어났습니다.")

        def build(subsets: Mapping[str, Sequence[Any]]) -> Any:
            query = self._schemas.get(schema_name).table(table_name).select(selected_columns)
            for column, value in equal_filters.items():
                query = query.eq(column, value)
            for column, values in subsets.items():
                query = query.in_(column, list(values))
            for column, descending in order_fields:
                query = query.order(column, desc=descending)
            return query

        def read(subsets: Mapping[str, Sequence[Any]], ceiling: int) -> list[dict[str, Any]]:
            if page_size is None:
                query = build(subsets)
                if limit is not None:
                    query = query.limit(int(limit))
                return self._response_rows(query.execute())
            rows: list[dict[str, Any]] = []
            start = 0
            batch_size = int(page_size)
            while start < ceiling:
                end = min(start + batch_size, ceiling) - 1
                chunk = self._response_rows(build(subsets).range(start, end).execute())
                rows.extend(chunk)
                if len(chunk) < end - start + 1:
                    break
                start = end + 1
            return rows[:ceiling]

        ceiling = int(max_rows or limit or 20_000)
        splits = list(_membership_chunks(membership_filters))
        if len(splits) == 1:
            return read(splits[0], ceiling)

        # `in` 값은 URL에 그대로 실린다. 행 상한과 다른 벽이라 페이지네이션으로는
        # 풀리지 않고, 넘기면 PostgREST가 400을 준다 — 대시보드에서는 "실적 DB
        # 조회 실패" 한 줄로만 보인다. 한 행은 각 컬럼에서 정확히 한 조각에만
        # 속하므로 조각을 합쳐도 중복이 생기지 않는다.
        merged: list[dict[str, Any]] = []
        for subsets in splits:
            merged.extend(read(subsets, ceiling))
        for column, descending in reversed(order_fields):
            merged.sort(key=lambda row, c=column: (row.get(c) is None, row.get(c)), reverse=descending)
        return merged[:ceiling]

    def select_function_rows(
        self,
        *,
        schema: str,
        function: str,
        arguments: Mapping[str, Any] | None = None,
        page_size: int | None = None,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        """allowlist에 있는 읽기 전용 SQL 함수의 결과 행만 읽는다.

        비공개 스키마(`alerts`)의 사실에 닿는 유일한 경로다. 이름과 인자 이름이
        allowlist와 정확히 같지 않으면 호출하지 않고 거부한다. 상태를 바꾸는 RPC는
        allowlist에 올리지 않으므로 이 경로로 실행할 수 없다.
        """

        schema_name = self._identifier(schema)
        function_name = self._identifier(function)
        allowed = self.READ_ONLY_FUNCTIONS.get(function_name)
        if allowed is None:
            raise DashboardDataError("읽기 전용 allowlist에 없는 함수입니다.")
        parameters = dict(arguments or {})
        if not set(parameters).issubset(allowed):
            raise DashboardDataError("허용되지 않은 함수 인자입니다.")

        def build() -> Any:
            return self._schemas.get(schema_name).rpc(function_name, parameters)

        if page_size is None:
            return self._response_rows(build().execute())
        if not 1 <= int(page_size) <= 1_000:
            raise DashboardDataError("함수 page_size 범위를 벗어났습니다.")
        ceiling = int(max_rows or 20_000)
        if not 1 <= ceiling <= 200_000:
            raise DashboardDataError("함수 max_rows 범위를 벗어났습니다.")
        rows: list[dict[str, Any]] = []
        start = 0
        batch_size = int(page_size)
        while start < ceiling:
            end = min(start + batch_size, ceiling) - 1
            chunk = self._response_rows(build().range(start, end).execute())
            rows.extend(chunk)
            if len(chunk) < end - start + 1:
                break
            start = end + 1
        return rows[:ceiling]


def _offline_mode() -> bool:
    return os.environ.get("DASHBOARD_OFFLINE", "").strip().lower() in _TRUE_VALUES


def _configured() -> bool:
    return bool(
        os.environ.get("SUPABASE_URL", "").strip()
        and os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    )


def _gateway() -> SelectOnlyGateway:
    from investment_agent.platform.db.postgres import service_client

    return SelectOnlyGateway(service_client())


def _preflight() -> DataResult | None:
    if _offline_mode():
        return DataResult.offline(source=DB_SOURCE)
    if not _configured():
        return DataResult.unconfigured(
            source=DB_SOURCE,
            message="SUPABASE_URL 또는 SUPABASE_SERVICE_KEY가 설정되지 않았습니다.",
        )
    return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        current = value
        return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        current = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current
    except ValueError:
        try:
            current_date = date.fromisoformat(text)
        except ValueError:
            return None
        return datetime(current_date.year, current_date.month, current_date.day, tzinfo=timezone.utc)


def _latest_at(groups: Sequence[tuple[Sequence[Mapping[str, Any]], Sequence[str]]]) -> str | None:
    candidates: list[datetime] = []
    for rows, fields in groups:
        for row in rows:
            for field in fields:
                parsed = _as_datetime(row.get(field))
                if parsed is not None:
                    candidates.append(parsed.astimezone(timezone.utc))
                    break
    return normalize_observed_at(max(candidates)) if candidates else None


def _empty_or_ok(
    *,
    rows: list[dict[str, Any]],
    source: str,
    observed_at: object | None,
    empty_message: str,
) -> DataResult:
    if not rows:
        return DataResult.empty(source=source, observed_at=observed_at, message=empty_message)
    return DataResult.ok(rows=rows, source=source, observed_at=observed_at)


def _active_watchlist_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """SQL의 ``cardinality(sources) > 0`` 활성 조건을 메모리에서 그대로 적용한다."""

    active: list[dict[str, Any]] = []
    for row in rows:
        sources = row.get("sources")
        has_source = (
            isinstance(sources, Sequence)
            and not isinstance(sources, (str, bytes))
            and len(sources) > 0
        )
        if has_source and row.get("removed_at") is None:
            active.append(dict(row))
    return active


def _chunks(values: Sequence[str], size: int) -> list[tuple[str, ...]]:
    return [tuple(values[index:index + size]) for index in range(0, len(values), size)]


def _watchlist_rows(
    gateway: SelectOnlyGateway,
    *,
    ticker: str | None = None,
    require_fundamentals: bool = False,
) -> list[dict[str, Any]]:
    """v1 universe의 활성 관심 기업을 대표 종목 표기와 함께 읽는다."""

    rows = gateway.select_rows(
        schema=SCHEMA_UNIVERSE,
        table=T_ENTITIES,
        columns="cik,watchlist_sources,watch_from,is_watchlisted,watchlist_removed_at,updated_at",
        equal={"is_watchlisted": True},
        order=(("cik", False),),
        page_size=1_000,
        max_rows=20_000,
    )
    ciks = [str(row["cik"]) for row in rows]
    securities = (
        gateway.select_rows(
            schema=SCHEMA_UNIVERSE,
            table=T_SECURITIES,
            columns="security_id,ticker,cik,is_tracked",
            in_values={"cik": ciks},
            # 한 회사에 클래스가 여럿이면 ticker 오름차순 첫 종목이 대표다.
            order=(("ticker", False),),
            page_size=1_000,
            max_rows=20_000,
        )
        if ciks
        else []
    )
    representative: dict[str, dict[str, Any]] = {}
    for row in securities:
        if row.get("is_tracked"):
            representative.setdefault(str(row["cik"]), row)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        security = representative.get(str(row["cik"]))
        if security is None:
            continue
        normalized.append({
            "cik": str(row["cik"]),
            "id": int(security["security_id"]),
            "security_id": int(security["security_id"]),
            "ticker": str(security["ticker"]),
            "sources": list(row.get("watchlist_sources") or []),
            "watch_from": row.get("watch_from"),
            "is_active": bool(row.get("is_watchlisted")),
            "removed_at": row.get("watchlist_removed_at"),
            "updated_at": row.get("updated_at"),
        })
    active = _active_watchlist_rows(normalized)
    del require_fundamentals  # v1에서 이 reader는 fundamentals watchlist 하나만 읽는다.
    if ticker:
        symbol = str(ticker).strip().upper()
        active = [row for row in active if str(row.get("ticker") or "").upper() == symbol]
    return active


@cache_data(ttl="2m", max_entries=2)
def load_macro_data() -> DataResult:
    """핵심 5개 지표의 메타데이터와 최신 관측 구간을 읽는다."""

    blocked = _preflight()
    if blocked:
        return blocked
    source = f"{DB_SOURCE} · reporting.macro_series/macro_observations"
    try:
        indicator_result = load_reporting_view(
            "macro_series", in_values={"series_id": MACRO_KPI_SERIES}
        )
        observation_result = load_reporting_view(
            "macro_observations", in_values={"series_id": MACRO_KPI_SERIES}
        )
        if indicator_result.status in {"error", "offline", "unconfigured"}:
            return indicator_result
        if observation_result.status in {"error", "offline", "unconfigured"}:
            return observation_result
        indicators = indicator_result.rows
        observations = observation_result.rows
        payload = {"indicators": indicators, "observations": observations}
        observed_at = _latest_at(((observations, ("obs_date",)),))
        if not observations:
            return DataResult.empty(
                source=source,
                value=payload,
                observed_at=observed_at,
                message="핵심 매크로 지표의 저장 관측값이 없습니다.",
            )
        return DataResult.ok(value=payload, source=source, observed_at=observed_at)
    except Exception as error:
        return DataResult.error(
            source=source,
            message=public_exception_message("매크로 DB 조회에 실패했습니다.", error),
        )


# 매크로 화면이 읽는 지표 집합. Discord 코어/감시 카드의 SSOT를 그대로 인용한다.
MACRO_LOOKBACK_DAYS = 400


@cache_data(ttl="15m", max_entries=64)
def load_ticker_data_quality(ticker: str) -> DataResult:
    """한 종목의 분할 이력과 회사 단위 시가총액 완전성을 읽는다."""

    symbol = str(ticker or "").strip().upper()
    source = f"{DB_SOURCE} · market.split_events/universe.securities"
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", symbol):
        return DataResult.blocked(source=source, message="유효한 종목 코드가 필요합니다.")
    blocked = _preflight()
    if blocked:
        return blocked
    payload: dict[str, list[dict[str, Any]]] = {"splits": [], "issuer": []}
    failures: list[str] = []
    try:
        gateway = _gateway()

        def select_dataset(dataset: str, **query: Any) -> None:
            try:
                rows = gateway.select_rows(**query)
                # 세그먼트는 표시용 파생값을 저장하지 않으므로 여기서 붙인다.
                payload[dataset] = (
                    enrich_segment_rows(rows)
                    if dataset in {"segment_metrics", "segment_all"} else rows
                )
            except Exception:
                failures.append(dataset)

        identity, _ = _security_identity(gateway, [symbol])
        security = identity.get(symbol)
        if security and security.get("security_id") is not None:
            split_rows = gateway.select_rows(
                schema=SCHEMA_MARKET,
                table=T_SPLIT_EVENTS,
                columns="security_id,action_date,split_ratio",
                equal={"security_id": int(security["security_id"])},
                order=(("action_date", True),),
                limit=60,
            )
            payload["splits"] = [
                {**row, "ticker": symbol} for row in split_rows
            ]
        # 밸류에이션 view는 v1에 없으므로 issuer에는 universe identity만 노출한다.
        try:
            cik_rows = gateway.select_rows(
                schema=SCHEMA_UNIVERSE,
                table=T_SECURITIES,
                columns="ticker,cik,security_id",
                equal={"ticker": symbol},
                limit=1,
            )
            if cik_rows:
                payload["issuer"] = [
                    {
                        "ticker": symbol,
                        "cik": cik_rows[0].get("cik"),
                        "security_id": cik_rows[0].get("security_id"),
                    }
                ]
        except Exception:
            failures.append("issuer")
        observed_at = _latest_at(
            ((payload["splits"], ("action_date",)),)
        )
        if failures and len(failures) == len(payload):
            return DataResult.error(
                source=source,
                value=payload,
                message=f"신뢰도 조회에 실패했습니다. 실패 데이터셋: {', '.join(failures)}",
            )
        if not any(payload.values()):
            return DataResult.empty(
                source=source,
                value=payload,
                observed_at=observed_at,
                message=f"{symbol}의 분할 이력·밸류에이션 완전성 기록이 없습니다.",
            )
        return DataResult.ok(
            value=payload,
            source=source,
            observed_at=observed_at,
            message=f"일부 데이터셋 조회 실패: {', '.join(failures)}" if failures else None,
        )
    except Exception as error:
        return DataResult.error(
            source=source,
            value=payload,
            message=public_exception_message("신뢰도 조회에 실패했습니다.", error),
        )


@cache_data(ttl="30m", max_entries=2)
def load_tickers() -> DataResult:
    """추적 종목과 활성 watchlist 속성을 한 목록으로 결합한다."""

    blocked = _preflight()
    if blocked:
        return blocked
    source = f"{DB_SOURCE} · universe.securities/universe.entities"
    try:
        gateway = _gateway()
        tracked_tickers = gateway.select_rows(
            schema=SCHEMA_UNIVERSE,
            table=T_SECURITIES,
            columns=(
                "ticker,cik,exchange_code,is_tracked"
            ),
            equal={"is_tracked": True},
            order=(("ticker", False),),
            page_size=1_000,
            max_rows=20_000,
        )
        tracked_tickers = [
            _display_security_profile(row)
            for row in _attach_entity_profiles(gateway, tracked_tickers)
        ]
        active_watchlist = _watchlist_rows(gateway)
        ticker_by_symbol = {
            str(row.get("ticker") or "").upper(): row
            for row in tracked_tickers
            if row.get("ticker")
        }
        active_symbols = sorted(
            {str(row.get("ticker") or "").upper() for row in active_watchlist if row.get("ticker")}
        )
        missing_symbols = [symbol for symbol in active_symbols if symbol not in ticker_by_symbol]
        for chunk in _chunks(missing_symbols, 150):
            metadata_rows = gateway.select_rows(
                schema=SCHEMA_UNIVERSE,
                table=T_SECURITIES,
                columns=(
                    "ticker,cik,exchange_code,is_tracked"
                ),
                in_values={"ticker": chunk},
                order=(("ticker", False),),
                limit=len(chunk),
            )
            metadata_rows = [
                _display_security_profile(row)
                for row in _attach_entity_profiles(gateway, metadata_rows)
            ]
            ticker_by_symbol.update(
                {
                    str(row.get("ticker") or "").upper(): row
                    for row in metadata_rows
                    if row.get("ticker")
                }
            )
        by_ticker: dict[str, list[dict[str, Any]]] = {}
        for row in active_watchlist:
            by_ticker.setdefault(str(row.get("ticker") or "").upper(), []).append(row)

        rows: list[dict[str, Any]] = []
        for symbol in sorted(ticker_by_symbol):
            ticker = ticker_by_symbol[symbol]
            symbol = str(ticker.get("ticker") or "").upper()
            memberships = by_ticker.get(symbol, [])
            rows.append(
                {
                    **ticker,
                    "watchlist_active": bool(memberships),
                    "watchlist_names": ["fundamentals"] if memberships else [],
                    "fundamentals_watchlist": bool(memberships),
                    "watchlist": memberships,
                }
            )
        observed_at = _latest_at(((active_watchlist, ("updated_at", "added_at")),))
        return _empty_or_ok(
            rows=rows,
            source=source,
            observed_at=observed_at,
            empty_message="추적 또는 활성 watchlist 종목이 없습니다.",
        )
    except Exception as error:
        return DataResult.error(
            source=source,
            message=public_exception_message("종목·watchlist DB 조회에 실패했습니다.", error),
        )


@cache_data(ttl="5m", max_entries=64)
def load_ai_data(ticker: str) -> DataResult:
    """선택 종목의 v1 판단·시그널·포트폴리오·승인 사실을 읽는다."""

    symbol = str(ticker or "").strip().upper()
    source = f"{DB_SOURCE} · reporting/execution"
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", symbol):
        return DataResult.blocked(source=source, message="유효한 종목 코드가 필요합니다.")
    blocked = _preflight()
    if blocked:
        return blocked
    payload: dict[str, list[dict[str, Any]]] = {
        "cases": [],
        "signals": [],
        "proposals": [],
        "risk_decisions": [],
        "approvals": [],
    }
    try:
        gateway = _gateway()
        case_rows = [
            row for row in read_local_rows("security_decisions", canonical_db=gateway)
            if row.get("ticker") == symbol
        ]
        case_rows.sort(key=lambda row: str(row.get("as_of_at") or ""), reverse=True)
        case_rows = case_rows[:12]
        cases = build_decision_cases_read_model(case_rows)
        securities = gateway.select_rows(
            schema=SCHEMA_UNIVERSE,
            table=T_SECURITIES,
            columns="security_id,ticker",
            equal={"ticker": symbol},
            limit=1,
        )
        security_id = securities[0].get("security_id") if securities else None
        signals = [row for row in read_runtime_rows("signals")
                   if security_id is not None and row.get("security_id") == security_id]
        signals.sort(key=lambda row: str(row.get("recorded_at") or ""), reverse=True)
        signals = signals[:40]
        proposal_rows = read_runtime_rows("portfolio_proposals")
        proposal_rows.sort(key=lambda row: str(row.get("as_of_at") or ""), reverse=True)
        proposal_rows = proposal_rows[:80]
        case_keys = {str(row.get("case_key")) for row in cases if row.get("case_key")}
        proposals = [
            row
            for row in proposal_rows
            if symbol in (row.get("weights") or {})
            or bool(case_keys.intersection(str(item) for item in (row.get("case_keys") or [])))
        ]
        proposal_ids = {
            str(row.get("proposal_id")) for row in proposals if row.get("proposal_id")
        }
        risk_rows = read_runtime_rows("risk_decisions")
        risk_rows.sort(key=lambda row: str(row.get("decided_at") or ""), reverse=True)
        risk_rows = risk_rows[:120]
        risk_decisions = [
            row
            for row in risk_rows
            if str(row.get("proposal_id")) in proposal_ids
            or symbol in (row.get("approved_weights") or {})
        ]
        approvals = [row for row in read_runtime_rows("approvals")
                     if str(row.get("proposal_id")) in proposal_ids]
        approvals.sort(key=lambda row: str(row.get("requested_at") or row.get("created_at") or ""), reverse=True)
        approvals = approvals[:80]
        payload = {
            "cases": cases,
            "signals": signals,
            "proposals": proposals,
            "risk_decisions": risk_decisions,
            "approvals": approvals,
        }
        observed_at = _latest_at(
            (
                (cases, ("as_of_at", "created_at")),
                (signals, ("recorded_at", "created_at")),
                (proposals, ("as_of_at", "created_at")),
                (risk_decisions, ("decided_at",)),
                (approvals, ("updated_at", "requested_at")),
            )
        )
        if not any(payload.values()):
            return DataResult.empty(
                source=source,
                value=payload,
                observed_at=observed_at,
                message=f"{symbol}의 저장된 AI 판단이 없습니다.",
            )
        return DataResult.ok(value=payload, source=source, observed_at=observed_at)
    except Exception as error:
        return DataResult.error(
            source=source,
            value=payload,
            message=public_exception_message("AI 투자 DB 조회에 실패했습니다.", error),
        )


@cache_data(ttl="2m", max_entries=2)
def load_execution_data() -> DataResult:
    """실행·체결·비용·정산 원장에서 화면에 안전한 관측 필드만 읽는다."""

    source = "로컬 Runtime · execution observability"
    payload: dict[str, list[dict[str, Any]]] = {
        "control_state": [],
        "intents": [],
        "approvals": [],
        "orders": [],
        "order_events": [],
        "fills": [],
        "tca_reports": [],
        "reconciliations": [],
    }
    queries = {
        "control_state": ("execution_control", "updated_at", 20),
        "intents": ("intents", "created_at", 120),
        "approvals": ("approvals", "requested_at", 160),
        "orders": ("orders", "updated_at", 400),
        "order_events": ("order_events", "occurred_at", 600),
        "fills": ("fills", "filled_at", 400),
        "reconciliations": ("reconciliation_runs", "started_at", 120),
    }
    failures: list[str] = []
    for key, (dataset, order_column, limit) in queries.items():
        try:
            rows = read_runtime_rows(dataset)
            rows.sort(key=lambda row: str(row.get(order_column) or ""), reverse=True)
            payload[key] = rows[:limit]
        except Exception:
            failures.append(key)
    observed_at = _latest_at(
        (
            (payload["control_state"], ("updated_at",)),
            (payload["intents"], ("completed_at", "created_at")),
            (payload["approvals"], ("updated_at", "requested_at")),
            (payload["orders"], ("updated_at", "submitted_at")),
            (payload["order_events"], ("occurred_at",)),
            (payload["fills"], ("filled_at", "created_at")),
            (payload["tca_reports"], ("created_at",)),
            (payload["reconciliations"], ("completed_at", "started_at")),
        )
    )
    # TCA 원문·상세 계산은 artifact 또는 Research 소유라 runtime 원장에 중복하지 않는다.
    if len(failures) == len(queries):
        return DataResult.error(
            source=source,
            value=payload,
            observed_at=observed_at,
            message="실행 관측 원장을 읽지 못했습니다.",
        )
    if not any(payload.values()):
        return DataResult.empty(
            source=source,
            value=payload,
            observed_at=observed_at,
            message="아직 저장된 실행·체결·정산 기록이 없습니다.",
        )
    return DataResult.ok(
        source=source,
        value=payload,
        observed_at=observed_at,
        message=f"일부 실행 데이터셋 조회 실패: {', '.join(failures)}" if failures else None,
    )


def _read_latest_account_snapshot() -> dict[str, Any]:
    """로컬 일일 계좌 사실 중 가장 최근 행을 화면 계약으로 투영한다."""

    accounts = read_runtime_rows("account_snapshots")
    if not accounts:
        return {}
    source_account = max(accounts, key=lambda row: str(row.get("captured_at") or ""))
    account = dict(source_account)
    account.setdefault("holdings", [])
    return account


@cache_data(ttl="30s", max_entries=2)
def load_latest_account_snapshot() -> DataResult:
    """실행 원장에 저장된 최신 계좌·보유 스냅샷만 읽는다.

    대시보드는 브로커 API나 ``raw_snapshot``을 읽지 않는다. 스냅샷 생성과 보관은
    execution이 소유하고, 화면은 명시된 관측 필드만 사용한다.
    """

    source = "로컬 Runtime · account_snapshots"
    try:
        payload = _read_latest_account_snapshot()
        if not payload:
            return DataResult.empty(
                source=source,
                value={"holdings": []},
                message="저장된 계좌 스냅샷이 없습니다.",
            )
        return DataResult.ok(
            source=source,
            value=payload,
            observed_at=payload.get("captured_at"),
        )
    except Exception as error:
        return DataResult.error(
            source=source,
            message=public_exception_message("계좌 스냅샷 조회에 실패했습니다.", error),
        )


@cache_data(ttl="2m", max_entries=2)
def load_alpha_lab_data() -> DataResult:
    """투자 엔진의 최근 입력·모델·신호·위험 심사 사실을 한 번에 읽는다.

    표마다 적재 주기가 다르므로 한 표의 실패가 전체 화면을 가리지 않게 부분 결과를
    보존한다. 집계값을 꾸미지 않고 최근 행만 제한해서 가져온 뒤 화면에서 계산한다.
    """

    source = "로컬 Research/Runtime · 투자 엔진"
    payload: dict[str, list[dict[str, Any]]] = {
        "decision_runs": [],
        "signal_runs": [],
        "market_regimes": [],
        "candidate_ranks": [],
        "event_features": [],
        "model_artifacts": [],
        "ticker_signals": [],
        "portfolio_proposals": [],
        "risk_decisions": [],
        "portfolio_evaluations": [],
        "promotions": [],
        "training_samples": [],
        "approvals": [],
    }
    failures: list[str] = []
    # Research는 v1 Supabase schema가 아니라 동일한 local DuckDB를 읽는다.
    for key, dataset in (
        ("market_regimes", "market_regimes"),
        ("candidate_ranks", "candidate_ranks"),
        ("event_features", "event_feature_snapshots"),
        ("training_samples", "training_samples"),
        ("portfolio_evaluations", "portfolio_evaluations"),
    ):
        try:
            payload[key] = load_local_research_records(dataset)
        except Exception:
            failures.append(key)

    queries = {
        "decision_runs": ("decision_runs", "started_at", 20),
        "signal_runs": ("signal_runs", "completed_at", 20),
        "ticker_signals": ("signals", "recorded_at", 200),
        "portfolio_proposals": ("portfolio_proposals", "as_of_at", 80),
        "risk_decisions": ("risk_decisions", "decided_at", 120),
        "promotions": ("model_promotions", "created_at", 80),
    }
    for key, (dataset, order_column, limit) in queries.items():
        try:
            rows = read_runtime_rows(dataset)
            rows.sort(key=lambda row: str(row.get(order_column) or ""), reverse=True)
            payload[key] = rows[:limit]
        except Exception:
            failures.append(key)

    try:
        rows = read_runtime_rows("approvals")
        rows.sort(key=lambda row: str(row.get("requested_at") or row.get("created_at") or ""), reverse=True)
        payload["approvals"] = rows[:80]
    except Exception:
        failures.append("approvals")
    try:
        rows = read_local_rows("current_model_stage")
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        payload["model_artifacts"] = rows[:60]
    except Exception:
        failures.append("model_artifacts")

    observed_at = _latest_at(
        (
            (payload["decision_runs"], ("finished_at", "started_at")),
            (payload["signal_runs"], ("completed_at", "created_at")),
            (payload["market_regimes"], ("as_of_at", "created_at")),
            (payload["candidate_ranks"], ("as_of_at", "created_at")),
            (payload["event_features"], ("as_of_at", "created_at")),
            (payload["model_artifacts"], ("created_at",)),
            (payload["ticker_signals"], ("recorded_at", "created_at")),
            (payload["portfolio_proposals"], ("as_of_at", "created_at")),
            (payload["risk_decisions"], ("decided_at",)),
            (payload["portfolio_evaluations"], ("evaluated_at",)),
            (payload["promotions"], ("approved_at", "created_at")),
            (payload["training_samples"], ("as_of_at", "created_at")),
            (payload["approvals"], ("updated_at", "requested_at")),
        )
    )
    if len(failures) == len(payload):
        return DataResult.error(
            source=source,
            value=payload,
            observed_at=observed_at,
            message="투자 엔진 데이터셋을 읽지 못했습니다.",
        )
    if not any(payload.values()):
        return DataResult.empty(
            source=source,
            value=payload,
            observed_at=observed_at,
            message="아직 저장된 투자 엔진 실행 결과가 없습니다.",
        )
    message = f"일부 데이터셋 조회 실패: {', '.join(failures)}" if failures else None
    return DataResult.ok(
        source=source,
        value=payload,
        observed_at=observed_at,
        message=message,
    )


@cache_data(ttl="15m", max_entries=32)
def load_earnings_data(ticker: str | None = None, *, section: str = "all") -> DataResult:
    """SEC 재무·공시·시장 예상치·활성 실적 watchlist를 읽는다."""

    symbol = str(ticker or "").strip().upper() or None
    source = f"{DB_SOURCE} · fundamentals expectations · {section}"
    if symbol and not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", symbol):
        return DataResult.blocked(source=source, message="유효한 종목 코드가 필요합니다.")
    blocked = _preflight()
    if blocked:
        return blocked
    payload: dict[str, list[dict[str, Any]]] = {
        "core": [],
        "filings": [],
        "consensus": [],
        "watchlist": [],
        "ticker_profiles": [],
        "earnings_flash": [],
    }
    scopes = {
        "⚡ 실적 속보 (8-K)": {"core", "earnings_flash", "watchlist", "ticker_profiles"},
        "발표 예정": {"core", "consensus", "watchlist", "ticker_profiles"},
        "발표 결과": {"core", "consensus", "watchlist"},
        "재무 추이": {"core", "watchlist"},
        "공시 근거": {"core", "filings", "watchlist"},
        "Discord 카드 전체": {"core", "watchlist", "ticker_profiles"},
        # 확장 분석은 종목 선택만 필요하다. 실제 근거는 load_earnings_extended가 섹션별로 읽는다.
        "확장 분석": {"watchlist"},
        "all": set(payload),
    }
    requested = scopes.get(section)
    if requested is None:
        return DataResult.blocked(source=source, message="지원하지 않는 실적 보기입니다.")
    try:
        gateway = _gateway()
        ticker_filter = {"ticker": symbol} if symbol else None

        def select_dataset(dataset: str, **query: Any) -> list[dict[str, Any]]:
            return gateway.select_rows(**query) if dataset in requested else []

        # 관심종목을 먼저 읽는다. 모든 보기가 이 목록으로 걸러지므로, 나머지 조회도
        # 처음부터 이 티커들로 좁혀야 한다 — 전체를 읽으면 PostgREST 상한에서 잘리고
        # 잘린 자리에 전년 동기 행이 사라진다.
        watchlist = (
            _watchlist_rows(gateway, ticker=symbol, require_fundamentals=True)
            if "watchlist" in requested
            else []
        )
        tracked_tickers = sorted(
            {
                str(row.get("ticker") or "").strip().upper()
                for row in watchlist
                if row.get("ticker")
            }
        )
        # 종목을 명시하면 eq 하나로, 아니면 활성 관심종목 목록으로 조회 범위를 정한다.
        selected_tickers = [symbol] if symbol else tracked_tickers
        core = (
            _canonical_financial_rows(gateway, selected_tickers, limit=240 if symbol else 8_000)
            if "core" in requested else []
        )
        filings = (
            _canonical_processing_rows(
                gateway, selected_tickers, content_type=FILING_CONTENT_COMPANY
            ) if "filings" in requested else []
        )
        by_ticker, _by_cik = _security_identity(gateway, selected_tickers)
        security_ids = [int(row["security_id"]) for row in by_ticker.values() if row.get("security_id") is not None]
        consensus = []
        if "consensus" in requested and security_ids:
            consensus = gateway.select_rows(
                schema=SCHEMA_FUNDAMENTALS,
                table=T_EARNINGS_ESTIMATES,
                columns=_CONSENSUS_COLUMNS,
                in_values={"security_id": sorted(set(security_ids))},
                order=(("snapshot_date", True), ("target_fiscal_year", True)),
                page_size=1_000,
                max_rows=5_000,
            )
            ticker_by_id = {
                int(row["security_id"]): str(row["ticker"]).upper()
                for row in by_ticker.values() if row.get("security_id") is not None
            }
            consensus = [
                {**row, "ticker": ticker_by_id.get(int(row["security_id"]))}
                for row in consensus if ticker_by_id.get(int(row["security_id"]))
            ]

        ticker_profiles = select_dataset(
            "ticker_profiles",
            schema=SCHEMA_UNIVERSE,
            table=T_SECURITIES,
            columns="ticker,cik",
            in_values={"ticker": tracked_tickers},
            order=(("ticker", False),),
            page_size=1_000,
            max_rows=2_000,
        )
        ticker_profiles = [
            _display_security_profile(row)
            for row in _attach_entity_profiles(gateway, ticker_profiles)
        ]
        earnings_flash = select_dataset(
            "earnings_flash",
            schema=SCHEMA_REPORTING,
            table=V_EARNINGS_SURPRISE,
            columns=(
                "ticker,cik,fiscal_year,fiscal_period,period_end,filing_date,available_at,accession_no,"
                "revenue_actual,eps_actual,eps_estimate,revenue_estimate,estimate_snapshot_date,"
                "eps_analysts,eps_surprise_pct,revenue_surprise_pct,guidance_summary,"
                "operating_income_actual,net_income_actual,press_release_url"
            ),
            **({"equal": ticker_filter} if symbol else {"in_values": {"ticker": tracked_tickers}}),
            order=(("filing_date", True), ("ticker", False)),
            **({"limit": 60} if symbol else {"page_size": 1_000, "max_rows": 2_000}),
        ) if "earnings_flash" in requested else []
        payload = {
            "core": core,
            "filings": filings,
            "consensus": consensus,
            "watchlist": watchlist,
            "ticker_profiles": ticker_profiles,
            "earnings_flash": earnings_flash,
        }
        observed_at = _latest_at(
            (
                (core, ("updated_at", "filed_at")),
                (filings, ("updated_at", "filing_date")),
                (earnings_flash, ("collected_at", "filed_at")),
                (consensus, ("collected_at", "snapshot_date")),
                (watchlist, ("updated_at",)),
            )
        )
        if not any(payload.values()):
            return DataResult.empty(
                source=source,
                value=payload,
                observed_at=observed_at,
                message="저장된 실적·컨센서스 데이터가 없습니다.",
            )
        return DataResult.ok(value=payload, source=source, observed_at=observed_at)
    except Exception as error:
        return DataResult.error(
            source=source,
            value=payload,
            message=public_exception_message("실적 DB 조회에 실패했습니다.", error),
        )


@cache_data(ttl="15m", max_entries=64)
def load_earnings_discord_support(ticker: str, *, section: str = "all") -> DataResult:
    """Discord 실적 카드의 상세 근거를 선택 종목에 한해 읽는다.

    기본 실적 화면은 :func:`load_earnings_data`만 사용하고, 사용자가
    Discord 상세 뷰와 내부 섹션을 선택했을 때만 이 로더를 호출한다. 실제 알림의
    건전성·TTM·밸류에이션·컨센서스·가격/주식수·세그먼트 중 선택 섹션의 SELECT
    근거만 반환하며, ``section='all'``은 명시적인 원자료/검증 용도다.
    모든 파생값은 화면 메모리에서 계산한다.
    """

    symbol = str(ticker or "").strip().upper()
    source = f"{DB_SOURCE} · Discord #실적-리포트 상세 근거 · {section}"
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", symbol):
        return DataResult.blocked(source=source, message="유효한 종목 코드가 필요합니다.")
    blocked = _preflight()
    if blocked:
        return blocked

    payload: dict[str, list[dict[str, Any]]] = {
        "metrics": [],
        "ttm": [],
        "valuation": [],
        "earnings_estimates": [],
        "price_history": [],
        "shares_outstanding_history": [],
        "segment_metrics": [],
        "segment_processing": [],
    }
    scopes = {
        # 결과 화면의 기본. 카드 요약과 시장 기대를 한 화면에 함께 그리므로 두 범위를 합친다.
        "요약": {"metrics", "earnings_estimates"},
        "카드 요약": {"metrics"},
        "시장 기대": {"earnings_estimates"},
        "실적·현금흐름": {"metrics", "earnings_estimates"},
        "가격·밸류": {"valuation", "price_history"},
        "건전성·이익의 질": {"metrics", "ttm"},
        "기술·주주환원": {
            "earnings_estimates", "price_history", "shares_outstanding_history",
        },
        "세그먼트": {"segment_metrics", "segment_processing"},
        "원자료": set(payload),
        "all": set(payload),
    }
    requested = scopes.get(section)
    if requested is None:
        return DataResult.blocked(source=source, message="지원하지 않는 Discord 실적 섹션입니다.")
    failures: list[str] = []
    attempted: list[str] = []
    try:
        gateway = _gateway()
        def select_dataset(dataset: str, **query: Any) -> None:
            """한 선택 소스의 실패가 다른 실제 결과를 지우지 않게 격리한다."""

            if dataset not in requested:
                return
            attempted.append(dataset)
            try:
                rows = gateway.select_rows(**query)
                # 세그먼트는 표시용 파생값을 저장하지 않으므로 여기서 붙인다.
                payload[dataset] = (
                    enrich_segment_rows(rows)
                    if dataset in {"segment_metrics", "segment_all"} else rows
                )
            except Exception:
                failures.append(dataset)


        # v1에서는 TTM·밸류에이션을 저장된 과거 view로 읽지 않는다. 필요한
        # 원장은 canonical 테이블에서 확인하고, 파생 화면은 별도 계산 계층이
        # 제공할 때만 노출한다.
        if "metrics" in requested:
            payload["metrics"] = []
        if "ttm" in requested:
            payload["ttm"] = []
        if "valuation" in requested:
            payload["valuation"] = []
        if "price_history" in requested:
            payload["price_history"] = _canonical_price_rows(gateway, [symbol])
        if "shares_outstanding_history" in requested:
            payload["shares_outstanding_history"] = _canonical_share_rows(gateway, [symbol])
        # 관측(observed) 스냅샷만 올린다. reconstructed는 소급 재구성이라 공시 전
        # 시점 근거로 쓰면 안 된다.
        estimate_identity = (
            _security_identity(gateway, [symbol])[0]
            if "earnings_estimates" in requested else {}
        )
        estimate_ids = [
            int(row["security_id"])
            for row in estimate_identity.values()
            if row.get("security_id") is not None
        ]
        select_dataset(
            "earnings_estimates",
            schema=SCHEMA_FUNDAMENTALS,
            table=T_EARNINGS_ESTIMATES,
            columns=_CONSENSUS_COLUMNS,
            equal={"snapshot_kind": CONSENSUS_KIND_OBSERVED},
            in_values={"security_id": estimate_ids},
            order=(("snapshot_date", True), ("target_fiscal_year", True)),
            limit=240,
        )
        if "earnings_estimates" in requested:
            ticker_by_id = {
                int(row["security_id"]): symbol
                for row in estimate_identity.values() if row.get("security_id") is not None
            }
            payload["earnings_estimates"] = [
                {**row, "ticker": ticker_by_id.get(int(row["security_id"]))}
                for row in payload["earnings_estimates"]
                if ticker_by_id.get(int(row["security_id"]))
            ]
        if "segment_metrics" in requested:
            payload["segment_metrics"] = enrich_segment_rows(
                _canonical_segment_rows(gateway, [symbol], limit=600)
            )
        if "segment_processing" in requested:
            payload["segment_processing"] = _canonical_processing_rows(
                gateway, [symbol], content_type=FILING_CONTENT_SEGMENTS
            )

        observed_at = _latest_at(
            (
                (payload["metrics"], ("period_end",)),
                (payload["ttm"], ("period_end",)),
                (payload["valuation"], ("price_date", "period_end")),
                (payload["earnings_estimates"], ("collected_at", "snapshot_date")),
                (payload["price_history"], ("trade_date",)),
                (payload["shares_outstanding_history"], ("ingested_at", "as_of_date")),
                (payload["segment_metrics"], ("period_end",)),
                (payload["segment_processing"], ("updated_at", "filing_date")),
            )
        )

        failed_text = ", ".join(failures)
        if attempted and len(failures) == len(attempted):
            return DataResult.error(
                source=source,
                value=payload,
                observed_at=observed_at,
                message=f"Discord 실적 상세 DB 조회에 실패했습니다. 실패 데이터셋: {failed_text}",
            )

        if not any(payload.values()):
            suffix = f" 일부 조회 실패: {failed_text}" if failures else ""
            return DataResult.empty(
                source=source,
                value=payload,
                observed_at=observed_at,
                message=f"{symbol}의 Discord 실적 상세 근거가 저장되어 있지 않습니다.{suffix}",
            )
        message = f"일부 상세 데이터셋 조회 실패: {failed_text}" if failures else None
        return DataResult.ok(
            value=payload,
            source=source,
            observed_at=observed_at,
            message=message,
        )
    except Exception as error:
        failed_text = ", ".join(failures or payload.keys())
        return DataResult.error(
            source=source,
            value=payload,
            message=(
                f"{public_exception_message('Discord 실적 상세 DB 조회에 실패했습니다.', error)} "
                f"실패 데이터셋: {failed_text}"
            ),
        )


EXTENDED_SECTIONS: tuple[str, ...] = (
    "성장·마진",
    "업종 특수 재무",
    "기술 지표",
    "세그먼트 전 축",
    "수집·발송 감사",
)


@cache_data(ttl="15m", max_entries=64)
def load_earnings_extended(ticker: str, *, section: str = "all") -> DataResult:
    """Discord 실적 카드가 싣지 않는 확장 근거를 선택 섹션만 읽는다.

    카드는 지면이 좁아 대표 축 하나·상위 몇 행·현재 분기만 싣는다. 화면은 그 제약이
    없으므로 성장 뷰, 업종 특수 계정, 저장된 기술 지표, **모든** 세그먼트 축의 다기간
    이력, 수집·발송 감사 장부를 따로 읽는다. 선택하지 않은 섹션의 SELECT는 실행하지
    않고, 한 데이터셋 실패가 다른 성공 결과를 지우지 않는다.
    """

    symbol = str(ticker or "").strip().upper()
    source = f"{DB_SOURCE} · 실적 확장 근거 · {section}"
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", symbol):
        return DataResult.blocked(source=source, message="유효한 종목 코드가 필요합니다.")
    blocked = _preflight()
    if blocked:
        return blocked

    payload: dict[str, list[dict[str, Any]]] = {
        "growth": [],
        "industry": [],
        "tech_daily": [],
        "tech_view": [],
        "oscillators": [],
        "segment_all": [],
        "segment_processing": [],
        "filing_ledger": [],
        "notify_log": [],
    }
    scopes = {
        "성장·마진": {"growth"},
        "업종 특수 재무": {"industry"},
        "기술 지표": {"tech_daily", "tech_view", "oscillators"},
        "세그먼트 전 축": {"segment_all", "segment_processing"},
        "수집·발송 감사": {"filing_ledger", "notify_log"},
        "all": set(payload),
    }
    requested = scopes.get(section)
    if requested is None:
        return DataResult.blocked(source=source, message="지원하지 않는 실적 확장 섹션입니다.")

    failures: list[str] = []
    try:
        gateway = _gateway()
        def select_dataset(dataset: str, **query: Any) -> None:
            """선택 안 한 소스는 건너뛰고, 한 소스 실패를 그 소스에만 가둔다."""

            if dataset not in requested:
                return
            try:
                rows = gateway.select_rows(**query)
                # 세그먼트는 표시용 파생값을 저장하지 않으므로 여기서 붙인다.
                payload[dataset] = (
                    enrich_segment_rows(rows)
                    if dataset in {"segment_metrics", "segment_all"} else rows
                )
            except Exception:
                failures.append(dataset)

        # 성장률과 업종 특수 계정은 같은 canonical financials에서 읽는다.
        canonical_rows = (
            _canonical_financial_rows(gateway, [symbol], limit=120)
            if requested & {"growth", "industry"} else []
        )
        if "growth" in requested:
            payload["growth"] = [
                {key: row.get(key) for key in (
                    "ticker", "fiscal_year", "fiscal_period", "period_end", "filed_at",
                    "revenue", "net_income", "operating_income_loss", "gross_profit",
                )}
                for row in canonical_rows
            ]
        if "industry" in requested:
            payload["industry"] = canonical_rows
        # 재계산 가능한 Research feature는 Supabase production schema가 아니라
        # 로컬 DuckDB가 owner다. 비재귀 지표는 현재 이 화면의 저장 계약에 없으므로
        # 빈 결과를 반환하고, 존재하지 않는 production view를 호출하지 않는다.
        if "tech_daily" in requested:
            payload["tech_daily"] = load_local_features(symbol, limit=520)
        payload["tech_view"] = []
        payload["oscillators"] = []
        # 전 축·다기간 추이. 카드는 대표 축 하나만 그리지만 여기서는 전부 본다.
        if "segment_all" in requested:
            payload["segment_all"] = enrich_segment_rows(
                _canonical_segment_rows(gateway, [symbol])
            )
        if "segment_processing" in requested:
            payload["segment_processing"] = _canonical_processing_rows(
                gateway, [symbol], content_type=FILING_CONTENT_SEGMENTS
            )
        if "filing_ledger" in requested:
            payload["filing_ledger"] = _canonical_processing_rows(
                gateway, [symbol], content_type=FILING_CONTENT_COMPANY
            )
        # 발송 상태는 외부 canonical DB가 아니라 로컬 runtime 원장이 소유한다.
        if "notify_log" in requested:
            try:
                payload["notify_log"] = [
                    row for row in read_runtime_rows("notification_outbox")
                    if row.get("producer") == "fundamentals"
                    and row.get("kind") == "fundamentals_earnings"
                    and row.get("entity_key") == symbol
                    and row.get("status") == "sent"
                ][:240]
            except Exception:
                failures.append("notify_log")

        filing_by_accession = {
            str(row.get("accession_no")): row
            for row in payload["filing_ledger"]
            if row.get("accession_no")
        }
        notify_rows: list[dict[str, Any]] = []
        prefix = f"report:{symbol}:"
        for row in payload["notify_log"]:
            key = str(row.get("notification_key") or "")
            accession_no = key[len(prefix):] if key.startswith(prefix) else ""
            filing = filing_by_accession.get(accession_no, {})
            notify_rows.append({
                "ticker": symbol,
                "accession_no": accession_no,
                "fiscal_year": filing.get("fiscal_year"),
                "fiscal_period": filing.get("fiscal_period"),
                "filed_at": filing.get("filing_date"),
                "sent_at": row.get("resolved_at"),
                "period_end": row.get("period_end"),
            })
        payload["notify_log"] = notify_rows

        observed_at = _latest_at(
            (
                (payload["growth"], ("period_end",)),
                (payload["industry"], ("ingested_at", "filed_at")),
                (payload["tech_daily"], ("ingested_at", "trade_date")),
                (payload["tech_view"], ("trade_date",)),
                (payload["oscillators"], ("trade_date",)),
                (payload["segment_all"], ("period_end",)),
                (payload["segment_processing"], ("updated_at", "filing_date")),
                (payload["filing_ledger"], ("updated_at", "filing_date")),
                (payload["notify_log"], ("sent_at", "filed_at")),
            )
        )
        failed_text = ", ".join(failures)
        if failures and len(failures) == len(requested):
            return DataResult.error(
                source=source,
                value=payload,
                observed_at=observed_at,
                message=f"실적 확장 DB 조회에 실패했습니다. 실패 데이터셋: {failed_text}",
            )
        if not any(payload.values()):
            suffix = f" 일부 조회 실패: {failed_text}" if failures else ""
            return DataResult.empty(
                source=source,
                value=payload,
                observed_at=observed_at,
                message=f"{symbol}의 확장 근거가 저장되어 있지 않습니다.{suffix}",
            )
        return DataResult.ok(
            value=payload,
            source=source,
            observed_at=observed_at,
            message=f"일부 확장 데이터셋 조회 실패: {failed_text}" if failures else None,
        )
    except Exception as error:
        failed_text = ", ".join(failures or sorted(requested))
        return DataResult.error(
            source=source,
            value=payload,
            message=(
                f"{public_exception_message('실적 확장 DB 조회에 실패했습니다.', error)} "
                f"실패 데이터셋: {failed_text}"
            ),
        )


@cache_data(ttl="30m", max_entries=2)
def load_guru_data() -> DataResult:
    """v1 institutional 원장을 대시보드 표시 계약으로 투영한다.

    13F의 정정 선택과 변화 계산은 institutional 도메인이 소유한다. 대시보드는
    v1 원천 표를 읽고, ticker 매핑을 붙인 뒤 화면이 필요한 평면 행만 전달한다.
    구 institutional Smart View는 v1에 존재하지 않으므로 조회하지 않는다.
    """

    blocked = _preflight()
    if blocked:
        return blocked
    source = f"{DB_SOURCE} · institutional 13F 원장"
    payload: dict[str, list[dict[str, Any]]] = {
        "managers": [],
        "filings": [],
        "positions": [],
        "cusip_map": [],
        "smart_changes": [],
    }
    try:
        gateway = _gateway()
        from investment_agent.reporting.readers.dashboard import guru_managers

        managers = guru_managers()
        manager_ciks = [str(row["manager_cik"]) for row in managers]
        filings = gateway.select_rows(
            schema=SCHEMA_INSTITUTIONAL,
            table=T_INSTITUTIONAL_FILINGS,
            columns=(
                "accession_no,manager_cik,period_end,form_type,report_type,filing_date,"
                "accepted_at,amendment_type,amendment_no,reported_value_usd,"
                "reported_line_count,confidential_omitted,source_url,content_sha256"
            ),
            in_values={"manager_cik": manager_ciks} if manager_ciks else None,
            order=(("manager_cik", False), ("period_end", True), ("accepted_at", True)),
            page_size=1_000,
            max_rows=20_000,
        )
        accessions = sorted({str(row["accession_no"]) for row in filings})
        positions = gateway.select_rows(
            schema=SCHEMA_INSTITUTIONAL,
            table=T_INSTITUTIONAL_POSITIONS,
            columns=(
                "accession_no,source_row_no,issuer_name,identifier,identifier_type,"
                "value_usd,quantity,quantity_type,position_kind"
            ),
            in_values={"accession_no": accessions} if accessions else None,
            order=(("accession_no", False), ("source_row_no", False)),
            page_size=1_000,
            max_rows=20_000,
        )
        identifier_values = sorted({str(row["identifier"]) for row in positions if row.get("identifier")})
        identifier_rows: list[dict[str, Any]] = []
        for start in range(0, len(identifier_values), 200):
            identifier_rows.extend(gateway.select_rows(
                schema=SCHEMA_UNIVERSE,
                table=T_SECURITY_IDENTIFIERS,
                columns="identifier,identifier_type,security_id,mapping_status,updated_at",
                in_values={"identifier": identifier_values[start:start + 200]},
                order=(("identifier", False), ("identifier_type", False), ("valid_from", True)),
                page_size=1_000,
                max_rows=20_000,
            ))
        security_ids = sorted({int(row["security_id"]) for row in identifier_rows if row.get("security_id") is not None})
        securities: list[dict[str, Any]] = []
        for start in range(0, len(security_ids), 200):
            securities.extend(gateway.select_rows(
                schema=SCHEMA_UNIVERSE,
                table=T_SECURITIES,
                columns="security_id,ticker",
                in_values={"security_id": security_ids[start:start + 200]},
                order=(("security_id", False),),
                page_size=1_000,
                max_rows=20_000,
            ))
        ticker_by_security_id = {int(row["security_id"]): row.get("ticker") for row in securities}
        cusip_map_by_identifier: dict[str, dict[str, Any]] = {}
        for row in identifier_rows:
            identifier = str(row.get("identifier") or "")
            if not identifier or identifier in cusip_map_by_identifier:
                continue
            security_id = row.get("security_id")
            cusip_map_by_identifier[identifier] = {
                "cusip": identifier,
                "ticker": ticker_by_security_id.get(int(security_id)) if security_id is not None else None,
                "updated_at": row.get("updated_at"),
            }
        cusip_map = list(cusip_map_by_identifier.values())
        ticker_by_cusip = {str(row["cusip"]): row.get("ticker") for row in cusip_map}
        display_positions = []
        for row in positions:
            display = dict(row)
            display["cusip"] = display.pop("identifier")
            display["ticker"] = ticker_by_cusip.get(str(display["cusip"]))
            display_positions.append(display)
        # 변화는 raw v1 원장으로 dashboard 계산 계층이 비교한다. 별도 Smart View를
        # 되살려 amendment 선택 규칙을 두 군데에 만들지 않는다.
        smart_changes: list[dict[str, Any]] = []
        payload = {
            "managers": managers,
            "filings": filings,
            "positions": display_positions,
            "cusip_map": cusip_map,
            "smart_changes": smart_changes,
        }
        observed_at = _latest_at(
            ((filings, ("accepted_at", "filing_date")), (cusip_map, ("updated_at",)))
        )
        if not managers and not filings:
            return DataResult.empty(
                source=source,
                value=payload,
                observed_at=observed_at,
                message="활성 13F 매니저 또는 공시 데이터가 없습니다.",
            )
        return DataResult.ok(value=payload, source=source, observed_at=observed_at)
    except Exception as error:
        return DataResult.error(
            source=source,
            value=payload,
            message=public_exception_message("v1 13F DB 조회에 실패했습니다.", error),
        )


@cache_data(ttl="15m", max_entries=2)
def load_strategy_data() -> DataResult:
    """전략 메타데이터와 실제 배분 이력을 읽는다."""

    source = "Research 로컬 · DuckDB strategy allocations"
    try:
        payload = load_local_strategy_data()
        strategies = payload["strategies"]
        allocations = payload["allocations"]
        observed_at = _latest_at(((allocations, ("apply_date", "created_at")),))
        if not strategies and not allocations:
            return DataResult.empty(
                source=source,
                value=payload,
                observed_at=observed_at,
                message="저장된 전략 또는 배분 이력이 없습니다.",
            )
        return DataResult.ok(value=payload, source=source, observed_at=observed_at)
    except Exception as error:
        return DataResult.error(
            source=source,
            message=public_exception_message("전략 DB 조회에 실패했습니다.", error),
        )


@cache_data(ttl="2m", max_entries=2)
def load_latest_target() -> DataResult:
    """최신 승인 비중과 그 입력 포트폴리오 제안을 함께 읽는다."""

    source = "로컬 Runtime · risk_decisions/portfolio_proposals"
    payload: dict[str, dict[str, Any] | None] = {"risk_decision": None, "proposal": None}
    try:
        decisions = [row for row in read_runtime_rows("risk_decisions") if row.get("is_approved")]
        decisions.sort(key=lambda row: str(row.get("decided_at") or ""), reverse=True)
        decisions = decisions[:1]
        risk_decision = decisions[0] if decisions else None
        proposals = [
            row for row in read_runtime_rows("portfolio_proposals")
            if risk_decision and row.get("proposal_id") == risk_decision.get("proposal_id")
        ]
        proposals.sort(key=lambda row: str(row.get("as_of_at") or ""), reverse=True)
        proposals = proposals[:1]
        proposal = proposals[0] if proposals else None
        payload = {"risk_decision": risk_decision, "proposal": proposal}
        observed_at = _latest_at(
            ((decisions, ("decided_at",)), (proposals, ("as_of_at", "created_at")))
        )
        if not risk_decision and not proposal:
            return DataResult.empty(
                source=source,
                value=payload,
                observed_at=observed_at,
                message="저장된 승인 목표 또는 포트폴리오 제안이 없습니다.",
            )
        return DataResult.ok(value=payload, source=source, observed_at=observed_at)
    except Exception as error:
        return DataResult.error(
            source=source,
            value=payload,
            message=public_exception_message("최신 승인 목표 DB 조회에 실패했습니다.", error),
        )


def load_reporting_view(
    view: str,
    *,
    equals: Mapping[str, Any] | None = None,
    in_values: Mapping[str, Sequence[Any]] | None = None,
    start: date | datetime | str | None = None,
    end: date | datetime | str | None = None,
) -> DataResult:
    """v1 reporting 뷰를 표준 ReportingQueries로 조회한다."""
    blocked = _preflight()
    if blocked:
        return blocked
    try:
        from investment_agent.platform.db.postgres import service_client
        from investment_agent.reporting.readers.financial import ReportingQueries

        client = service_client()
        queries = ReportingQueries.from_client(client, is_offline=_offline_mode())
        return queries.read(
            view,
            equals=equals,
            in_values=in_values,
            start=start,
            end=end,
        )
    except Exception as error:
        return DataResult.error(
            source=f"{DB_SOURCE} · reporting.{view}",
            message=public_exception_message(f"reporting.{view} 조회 실패", error),
        )


__all__ = [
    "DataResult",
    "EXTENDED_SECTIONS",
    "MACRO_KPI_SERIES",
    "MACRO_LOOKBACK_DAYS",
    "SelectOnlyGateway",
    "load_ai_data",
    "load_earnings_data",
    "load_earnings_discord_support",
    "load_earnings_extended",
    "load_execution_data",
    "load_guru_data",
    "load_latest_target",
    "load_latest_account_snapshot",
    "load_alpha_lab_data",
    "load_price_history",
    "load_macro_data",
    "load_reporting_view",
    "load_strategy_data",
    "load_ticker_data_quality",
    "load_tickers",
]
