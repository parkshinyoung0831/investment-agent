"""실적 화면이 읽는 재무·공시·컨센서스·세그먼트 read model. `SelectOnlyGateway`로만 저장소를 연다."""
from __future__ import annotations

from investment_agent.reporting.readers.select_only import (
    DB_SOURCE,
    SCHEMA_UNIVERSE,
    SelectOnlyGateway,
    T_SECURITIES,
    latest_at,
    open_gateway,
    preflight,
    security_identity,
)

import re
from collections.abc import Mapping, Sequence
from typing import Any
from investment_agent.reporting.services.fundamental_segments import enrich_segment_rows
from investment_agent.platform.cache import cache_data
from investment_agent.reporting.models import DataResult, public_exception_message
from investment_agent.reporting.readers.research import load_local_features

SCHEMA_FUNDAMENTALS = "fundamentals"


SCHEMA_MARKET = "market"


SCHEMA_REPORTING = "reporting"


SCHEMA_NOTIFICATIONS = "notifications"


T_NOTICES = "notices"


T_FINANCIALS = "financials"


T_FILINGS = "filings"


T_FILING_PROCESSING = "filing_processing"


T_EARNINGS_ESTIMATES = "earnings_estimates"


T_SHARE_CLASS_SNAPSHOTS = "share_class_snapshots"


T_SEGMENT_METRICS = "segment_metrics"


T_ENTITIES = "entities"


T_PRICES_DAILY = "prices_daily"


T_ACTIONS_DAILY = "actions_daily"


V_EARNINGS_SURPRISE = "earnings_surprise"


FILING_CONTENT_COMPANY = "company"


FILING_CONTENT_SEGMENTS = "segments"


CONSENSUS_KIND_OBSERVED = "captured_live"

EXTENDED_SECTIONS: tuple[str, ...] = (
    "성장·마진",
    "업종 특수 재무",
    "기술 지표",
    "세그먼트 전 축",
    "수집·발송 감사",
)


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


_FINANCIAL_COLUMNS = (
    "cik,fiscal_year,fiscal_period,accession_no,period_end,"
    "revenue,cost_of_goods_and_services_sold,gross_profit,"
    "research_and_development_expenses,selling_general_and_admin_expenses,"
    "operating_income_loss,interest_expense,"
    "pretax_income_loss,income_taxes,net_income,minority_interest_income,"
    "net_income_to_common_shareholders,"
    "eps_basic_gaap,eps_diluted_gaap,"
    "assets,current_assets_total,cash_and_cash_equivalents,short_term_investments,"
    "trade_receivables,inventories,property_plant_equipment_net,goodwill,"
    "intangible_assets_excluding_goodwill,"
    "liabilities,current_liabilities_total,"
    "trade_payables,short_term_debt,current_portion_of_long_term_debt,long_term_debt,"
    "total_debt_including_current,common_equity,minority_interest_balance,"
    "preferred_stock,retained_earnings,net_cash_from_operating_activities,"
    "net_cash_from_investing_activities,net_cash_from_financing_activities,"
    "depreciation_amortization_cf,stock_based_compensation_cf,"
    "capital_expenses,stock_repurchase_payments,common_dividends_paid,"
    "operating_lease_current_debt_equivalent,"
    "operating_lease_non_current_debt_equivalent,shares_average,"
    "shares_fully_diluted_average,net_interest_income,provision_for_credit_losses,"
    "net_loans_and_leases,total_deposits,is_liabilities_derived,"
    "mezzanine_equity,ingested_at"
)


_CONSENSUS_COLUMNS = (
    "security_id,target_fiscal_year,target_fiscal_period,target_period_end,snapshot_date,"
    "snapshot_kind,source,eps_basis,eps_avg,eps_low,eps_high,eps_analysts,"
    "revenue_avg,revenue_low,revenue_high,revenue_analysts,revisions_up_7d,"
    "revisions_up_30d,revisions_down_7d,revisions_down_30d,collected_at"
)


_FILING_PROCESSING_COLUMNS = (
    "accession_no,content_type,status,facts_count,rows_count,updated_at"
)


def _canonical_financial_rows(
    gateway: Any, tickers: Sequence[str], *, limit: int | None = None
) -> list[dict[str, Any]]:
    """canonical financials + filings를 dashboard 표시 행으로 투영한다."""
    by_ticker, by_cik = security_identity(gateway, tickers)
    if not by_cik:
        return []
    rows = gateway.select_rows(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_FINANCIALS,
        columns=_FINANCIAL_COLUMNS,
        in_values={"cik": sorted(by_cik)},
        order=(("period_end", True), ("cik", False), ("accession_no", False)),
        page_size=1_000,
        max_rows=limit or 20_000,
    )
    accessions = sorted({str(row["accession_no"]) for row in rows if row.get("accession_no")})
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
        filing = filing_by_accession.get(str(row.get("accession_no")), {})
        if not security or not filing.get("filing_date"):
            continue
        projected.append({
            **row,
            "accession_no": row.get("accession_no"),
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
    _by_ticker, by_cik = security_identity(gateway, tickers)
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
    _by_ticker, by_cik = security_identity(gateway, tickers)
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
    by_ticker, _by_cik = security_identity(gateway, tickers)
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


def _canonical_share_rows(
    gateway: Any, tickers: Sequence[str], *, limit: int = 240
) -> list[dict[str, Any]]:
    by_ticker, _by_cik = security_identity(gateway, tickers)
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


@cache_data(ttl="15m", max_entries=64)
def load_ticker_data_quality(ticker: str) -> DataResult:
    """한 종목의 분할 이력과 회사 단위 시가총액 완전성을 읽는다."""

    symbol = str(ticker or "").strip().upper()
    source = f"{DB_SOURCE} · market.actions_daily/universe.securities"
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", symbol):
        return DataResult.blocked(source=source, message="유효한 종목 코드가 필요합니다.")
    blocked = preflight()
    if blocked:
        return blocked
    payload: dict[str, list[dict[str, Any]]] = {"splits": [], "issuer": []}
    failures: list[str] = []
    try:
        gateway = open_gateway()

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

        identity, _ = security_identity(gateway, [symbol])
        security = identity.get(symbol)
        if security and security.get("security_id") is not None:
            action_rows = gateway.select_rows(
                schema=SCHEMA_MARKET,
                table=T_ACTIONS_DAILY,
                columns="security_id,action_date,split_ratio",
                equal={"security_id": int(security["security_id"])},
                order=(("action_date", True),),
                page_size=1_000,
                max_rows=5_000,
            )
            payload["splits"] = [
                {**row, "ticker": symbol} for row in action_rows if row.get("split_ratio") is not None
            ][:60]
        # 밸류에이션 view는 v1에 없으므로 issuer에는 universe identity만 노출한다.
        try:
            cik_rows = gateway.select_rows(
                schema=SCHEMA_UNIVERSE,
                table=T_SECURITIES,
                columns="ticker,cik,security_id",
                equal={"ticker": symbol, "is_active_listing": True},
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
        observed_at = latest_at(
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


@cache_data(ttl="15m", max_entries=32)
def load_earnings_data(ticker: str | None = None, *, section: str = "all") -> DataResult:
    """SEC 재무·공시·시장 예상치·활성 실적 watchlist를 읽는다."""

    symbol = str(ticker or "").strip().upper() or None
    source = f"{DB_SOURCE} · fundamentals expectations · {section}"
    if symbol and not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", symbol):
        return DataResult.blocked(source=source, message="유효한 종목 코드가 필요합니다.")
    blocked = preflight()
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
        gateway = open_gateway()
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
        by_ticker, _by_cik = security_identity(gateway, selected_tickers)
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
            equal={"is_active_listing": True},
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
                "eps_analysts,eps_surprise_ratio,revenue_surprise_ratio,guidance_summary,"
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
        observed_at = latest_at(
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
    blocked = preflight()
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
        gateway = open_gateway()
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


        # metrics·ttm·valuation은 v1에 저장 view가 없다. 셋 다 선언에서 이미 빈
        # 목록이고 여기서 채우지 않는다 — 조회를 빠뜨린 것이 아니라, 공시 시점
        # 배수와 TTM을 굳혀 둔 표가 v1에 없어서다. 화면은 그 사실을 빈 상태 문구로
        # 알린다. 파생 계산 계층이 그 계약을 갖추면 그때 여기에 연결한다.
        if "price_history" in requested:
            payload["price_history"] = _canonical_price_rows(gateway, [symbol])
        if "shares_outstanding_history" in requested:
            payload["shares_outstanding_history"] = _canonical_share_rows(gateway, [symbol])
        # 관측(observed) 스냅샷만 올린다. reconstructed는 소급 재구성이라 공시 전
        # 시점 근거로 쓰면 안 된다.
        estimate_identity = (
            security_identity(gateway, [symbol])[0]
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

        observed_at = latest_at(
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
    blocked = preflight()
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
        gateway = open_gateway()
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
        # 로컬 DuckDB가 owner다. tech_view·oscillators는 이 화면의 저장 계약에 없어
        # 선언의 빈 목록 그대로 둔다 — 없는 production view를 부르지 않기 위해서다.
        if "tech_daily" in requested:
            payload["tech_daily"] = load_local_features(symbol, limit=520)
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
        # 발송 이력은 로컬과 Actions가 함께 쓰는 알림 원장(Supabase notifications)이 소유한다.
        if "notify_log" in requested:
            try:
                payload["notify_log"] = gateway.select_rows(
                    schema=SCHEMA_NOTIFICATIONS,
                    table=T_NOTICES,
                    columns="occurrence,updated_at,fact_at",
                    equal={"topic": "earnings.report", "subject": symbol, "status": "sent"},
                    order=(("updated_at", True),),
                    limit=240,
                )
            except Exception:
                failures.append("notify_log")

        filing_by_accession = {
            str(row.get("accession_no")): row
            for row in payload["filing_ledger"]
            if row.get("accession_no")
        }
        notify_rows: list[dict[str, Any]] = []
        for row in payload["notify_log"]:
            accession_no = str(row.get("occurrence") or "")
            filing = filing_by_accession.get(accession_no, {})
            notify_rows.append({
                "ticker": symbol,
                "accession_no": accession_no,
                "fiscal_year": filing.get("fiscal_year"),
                "fiscal_period": filing.get("fiscal_period"),
                "filed_at": filing.get("filing_date"),
                "sent_at": row.get("updated_at"),
                "period_end": filing.get("report_date"),
            })
        payload["notify_log"] = notify_rows

        observed_at = latest_at(
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
