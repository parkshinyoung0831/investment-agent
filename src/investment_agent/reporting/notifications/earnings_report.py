"""펀더멘탈 실적 알림용 Supabase 접근.

이 파일에는 쿼리만 둔다 — 발송 후보 선정은 candidates.py, EV 계산은 capital.py가 맡는다.

읽기: 관심종목의 canonical financials·filings·가격/주식수 이력.
읽기: local runtime outbox에서 (ticker, accession_no) 발송 선점 상태만 확인 —
fundamentals 원장은 안 건드림.

관심종목은 universe.entities의 관심 컬럼을 단일 기준으로 사용한다.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from investment_agent.config import load_config
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger
from investment_agent.data.market.domain.actions import merge_corporate_actions
from investment_agent.data.market.repository import MarketRepository
from investment_agent.data.universe.repository import UniverseRepository
from investment_agent.notifications.earnings_report.capital import f, total_debt
from investment_agent.data.fundamentals.domain.services.classify_dimensions import display_member_name

# --- DB 식별자 (SSOT) ---------------------------------------------------
SCHEMA_FUNDAMENTALS = "fundamentals"
SCHEMA_MARKET = "market"
SCHEMA_REPORTING = "reporting"
SCHEMA_UNIVERSE = "universe"
T_FINANCIALS = "financials"
T_FILINGS = "filings"
T_SEGMENT_METRICS = "segment_metrics"
T_FILING_PROCESSING = "filing_processing"
T_ENTITIES = "entities"
T_EARNINGS_ESTIMATES = "earnings_estimates"
V_EARNINGS_SURPRISE = "earnings_surprise"
T_PRICES_DAILY = "prices_daily"
T_DIVIDEND_EVENTS = "dividend_events"
T_SPLIT_EVENTS = "split_events"
# ----------------------------------------------------------------------


log = get_logger(__name__)


class _V1Schema:
    def __init__(self, database: Database, name: str) -> None:
        self._database, self._name = database, name

    def table(self, name: str) -> Any:
        return self._database.table(self._name, name)


class _V1Client:
    def schema(self, name: str) -> _V1Schema:
        return _V1Schema(Database.from_config(load_config()), name)


v1 = _V1Client()


def database_for_config(config: Any | None = None) -> Database:
    """알림 실행기가 공유할 v1 reporting 연결을 만든다."""
    return Database.from_config(config or load_config())


def select_all_paged(factory: Any, *, order_by: str | None = None) -> list[dict]:
    """구독자 호출부도 v1 Database의 정렬·페이지 계약을 통과시킨다."""
    return Database.from_config(load_config()).select_paged(factory, order_by=order_by)

# 실적 카드를 만드는 보고 구간(분기 + 연간). 그 외 파생 행은 알림 대상 아님.
HEADLINE_PERIODS = ("Q1", "Q2", "Q3", "Q4", "FY")
QUARTERS = ("Q1", "Q2", "Q3", "Q4")
# 추세 차트(매출·EPS·현금흐름)에 쓰는 최근 분기 수.
TREND_QUARTERS = 13
# 실적 카드가 그리는 가격 구간. market 보존 한도(10년) 안이라 항상 조회 가능하다.
HISTORY_YEARS = 7

def watchlist_members() -> list[dict]:
    """v1 universe의 활성 펀더멘탈 관심종목을 반환한다."""
    members = UniverseRepository(Database.from_config(load_config())).watchlist_members("fundamentals")
    return [
        {
            "ticker": member.ticker,
            "security_id": member.security_id,
            "watch_from": member.watch_from.isoformat() if member.watch_from else None,
        }
        for member in members if member.is_active
    ]


_FINANCIAL_COLUMNS = (
    "cik,period_end,source_accession_no,source_filing_date,fiscal_year,fiscal_period,revenue,"
    "operating_income_loss,net_income,eps_diluted_gaap,assets,liabilities,"
    "is_liabilities_derived,common_equity,common_equity_scope,minority_interest_balance,"
    "mezzanine_equity,preferred_stock,net_cash_from_operating_activities,"
    "net_cash_from_investing_activities,net_cash_from_financing_activities,"
    "capital_expenses,cash_and_cash_equivalents,total_debt_including_current,"
    "short_term_debt,current_portion_of_long_term_debt,long_term_debt,"
    "operating_lease_current_debt_equivalent,operating_lease_non_current_debt_equivalent,"
    "common_dividends_paid,shares_fully_diluted_average,mapping_version"
)


def _financial_rows(tickers: list[str]) -> list[dict]:
    """v1 financials를 현재 ticker와 filing 사실로 펼친다."""
    if not tickers:
        return []
    database = Database.from_config(load_config())
    securities = UniverseRepository(database).securities_by_ticker(tickers)
    by_cik = {
        str(security.cik): ticker
        for ticker, security in securities.items() if security.cik
    }
    if not by_cik:
        return []
    rows = database.select_in_chunks(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_FINANCIALS,
        columns=_FINANCIAL_COLUMNS,
        filter_column="cik",
        values=list(by_cik),
        order_by="cik,period_end,source_accession_no",
    )
    accessions = [str(row["source_accession_no"]) for row in rows if row.get("source_accession_no")]
    filing_rows = database.select_in_chunks(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_FILINGS,
        columns="accession_no,filing_date,form_type,available_at",
        filter_column="accession_no",
        values=accessions,
        order_by="accession_no",
    ) if accessions else []
    filings = {str(row["accession_no"]): row for row in filing_rows}
    out: list[dict] = []
    for row in rows:
        accession_no = str(row.get("source_accession_no") or "")
        filing = filings.get(accession_no, {})
        ticker = by_cik.get(str(row.get("cik")))
        if not ticker or not filing.get("filing_date"):
            continue
        out.append({
            **row,
            "accession_no": accession_no,
            "ticker": ticker,
            "filed_at": filing.get("filing_date"),
            "form_type": filing.get("form_type"),
            "available_at": filing.get("available_at"),
        })
    return out


def processed_keys() -> set[tuple[str, str]]:
    """outbox에 등록된 (ticker, accession_no) 쌍 — 같은 공시 중복 차단용."""
    from investment_agent.notifications.outbox import Outbox

    out: set[tuple[str, str]] = set()
    for key in Outbox().sent_keys("fundamentals", kind="fundamentals_earnings"):
        if key.startswith("report:") and key.count(":") >= 2:
            _, ticker, accession_no = key.split(":", 2)
            out.add((ticker, accession_no))
    return out


def anomaly_keys(tickers: list[str]) -> set[tuple[str, int, str]]:
    """현재 재무 행에서 직접 계산한 대차대조표 불일치 키를 반환한다.

    운영 오류 원장을 조회하지 않는다. 재적재로 숫자가 고쳐지면 다음 조회에서 경고도
    자연스럽게 사라지므로, 과거 오류 기록과 현재 데이터 상태가 어긋나지 않는다.
    """
    rows = [row for row in _financial_rows(tickers) if row.get("fiscal_period") in HEADLINE_PERIODS]
    keys: set[tuple[str, int, str]] = set()
    for row in rows:
        assets = f(row.get("assets"))
        liabilities = f(row.get("liabilities"))
        equity = f(row.get("common_equity"))
        scope = str(row.get("common_equity_scope") or "unknown")
        if (
            assets in (None, 0.0)
            or liabilities is None
            or equity is None
            or scope == "unknown"
            or bool(row.get("is_liabilities_derived"))
        ):
            continue
        claims = liabilities + equity + (f(row.get("mezzanine_equity")) or 0.0)
        if scope != "stockholders_including_nci":
            claims += f(row.get("minority_interest_balance")) or 0.0
        if scope == "common":
            claims += f(row.get("preferred_stock")) or 0.0
        if abs(assets - claims) / abs(assets) <= 0.01:
            continue
        try:
            year = int(row["fiscal_year"])
        except (KeyError, TypeError, ValueError):
            continue
        ticker = str(row.get("ticker") or "")
        period = str(row.get("fiscal_period") or "")
        if ticker and period:
            keys.add((ticker, year, period))
    return keys


def load_headline_rows(tickers: list[str]) -> list[dict]:
    """v1 financials를 관심종목 ticker로 펼친 헤드라인 이력."""
    return [row for row in _financial_rows(tickers) if row.get("fiscal_period") in HEADLINE_PERIODS]


def load_sector_rows(tickers: list[str]) -> list[dict]:
    """v1에 별도 업종 wide 표가 없으므로 보조 업종 행은 만들지 않는다."""
    return []


def load_pending_keys(tickers: list[str]) -> list[dict]:
    """발송 여부 판정에만 필요한 최소 컬럼 — 렌더 의존성 설치 전 preflight용."""
    return [
        {
            key: row.get(key)
            for key in ("ticker", "fiscal_year", "fiscal_period", "period_end", "filed_at", "accession_no")
        }
        for row in _financial_rows(tickers)
        if row.get("fiscal_period") in HEADLINE_PERIODS
    ]


def load_health(tickers: list[str]) -> dict[str, dict]:
    """v1 reporting에 아직 합성 quality view가 없어 빈 선택 블록으로 둔다."""
    return {}


def load_valuation(tickers: list[str]) -> dict[str, dict]:
    """v1 선언에 valuation view가 없으므로 밸류에이션을 추정하지 않는다."""
    return {}


def load_earnings_estimates(tickers: list[str]) -> list[dict]:
    """관심종목의 실제 관측 분기 컨센서스 전부(행 선택은 카드 계층이 한다)."""
    if not tickers:
        return []
    database = Database.from_config(load_config())
    securities = UniverseRepository(database).securities_by_ticker(tickers)
    by_id = {security.security_id: ticker for ticker, security in securities.items()}
    if not by_id:
        return []
    rows = database.select_in_chunks(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_EARNINGS_ESTIMATES,
        columns=(
            "security_id,target_fiscal_year,target_fiscal_period,target_period_end,"
            "snapshot_date,snapshot_kind,source,source_horizon,eps_avg,eps_low,eps_high,eps_analysts,"
            "revenue_avg,revenue_low,revenue_high,revenue_analysts,revisions_up_7d,"
            "revisions_up_30d,revisions_down_7d,revisions_down_30d"
        ),
        filter_column="security_id",
        values=list(by_id),
        configure=lambda query: query.eq("snapshot_kind", "observed"),
        order_by="security_id,target_fiscal_year,target_fiscal_period,snapshot_date",
    )
    return [{**row, "ticker": by_id.get(int(row["security_id"]))} for row in rows]


def load_price_targets(tickers: list[str]) -> list[dict]:
    """목표주가는 저장하지 않는다 — 흡수된 스냅샷 표에 해당 컬럼이 없다."""
    return []


def load_surprise_history(tickers: list[str]) -> dict[str, list[dict]]:
    """v1 reporting view의 시점 결합 EPS 서프라이즈 이력을 읽는다.

    뷰가 `earnings_estimates`와 `earnings_results`를 발표일 기준으로 결합하므로,
    SEC GAAP 실제값을 임의의 현재 consensus와 다시 조합하지 않는다.
    """
    if not tickers:
        return {}
    normalized = sorted({str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()})
    if not normalized:
        return {}
    database = Database.from_config(load_config())
    rows = database.select_in_chunks(
        schema=SCHEMA_REPORTING,
        table=V_EARNINGS_SURPRISE,
        columns="ticker,period_end,eps_actual,eps_estimate,eps_surprise_pct",
        filter_column="ticker",
        values=normalized,
        order_by="ticker,period_end",
    )
    out = {ticker: [] for ticker in normalized}
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        period_end = row.get("period_end")
        if ticker not in out or not period_end:
            continue
        out[ticker].append({
            "ticker": ticker,
            "quarter_end": period_end,
            "eps_actual": row.get("eps_actual"),
            "eps_estimate": row.get("eps_estimate"),
            "surprise_pct": row.get("eps_surprise_pct"),
        })
    return out


def load_names(tickers: list[str]) -> dict[str, dict]:
    """표시용 회사명과 업종 프로필 판정용 SIC 분류를 읽는다."""
    securities = UniverseRepository(Database.from_config(load_config())).securities_by_ticker(tickers)
    ciks = [security.cik for security in securities.values() if security.cik]
    if not ciks:
        return {}
    rows = Database.from_config(load_config()).select_in_chunks(
        schema=SCHEMA_UNIVERSE,
        table=T_ENTITIES,
        columns="cik,company_name,company_name_ko,sic_industry_name,sic_division_name",
        filter_column="cik",
        values=ciks,
        order_by="cik",
    )
    by_cik = {str(row["cik"]): row for row in rows}
    return {
        ticker: {
            "ticker": ticker,
            "name": by_cik.get(str(security.cik), {}).get("company_name") or ticker,
            "name_ko": by_cik.get(str(security.cik), {}).get("company_name_ko"),
            "sic_industry": by_cik.get(str(security.cik), {}).get("sic_industry_name"),
            "sic_division": by_cik.get(str(security.cik), {}).get("sic_division_name"),
        }
        for ticker, security in securities.items()
    }


def load_price_history(tickers: list[str], years: int = HISTORY_YEARS) -> dict[str, list]:
    """티커별 일별 가격·배당·분할 이력."""
    if not tickers:
        return {}
    database = Database.from_config(load_config())
    securities = UniverseRepository(database).securities_by_ticker(tickers)
    by_id = {security.security_id: ticker for ticker, security in securities.items()}
    if not by_id:
        return {}
    cutoff = datetime.now(UTC).date() - timedelta(days=int(years * 365.25))
    market = MarketRepository(database)
    bars = market.bars(list(by_id), start=cutoff, end=datetime.now(UTC).date())
    dividends = market.dividends(list(by_id), since=cutoff)
    splits = market.splits(list(by_id), since=cutoff)
    prices = [
        {"ticker": by_id[bar.security_id], "trade_date": bar.trade_date.isoformat(),
         "close": bar.close, "volume": bar.volume}
        for bar in bars
    ]
    dividend_rows = [
        {"ticker": by_id[event.security_id], "ex_date": event.ex_date.isoformat(),
         "div_amount": event.div_amount}
        for event in dividends
    ]
    split_rows = [
        {"ticker": by_id[event.security_id], "action_date": event.action_date.isoformat(),
         "split_ratio": event.split_ratio}
        for event in splits
    ]
    out: dict[str, list] = {}
    for r in merge_corporate_actions(prices, dividend_rows, split_rows):
        out.setdefault(r["ticker"], []).append(r)
    return out


def load_quality_history(tickers: list[str]) -> dict[str, list[dict]]:
    """복합 차트용 분기별 부채/자본·유동비율을 원재무값으로 계산한다."""
    rows = [row for row in _financial_rows(tickers) if row.get("fiscal_period") in QUARTERS]
    out: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("period_end"):
            equity = f(r.get("common_equity"))
            assets = f(r.get("current_assets_total"))
            liabilities = f(r.get("current_liabilities_total"))
            out.setdefault(r["ticker"], []).append({
                "ticker": r["ticker"],
                "period_end": r["period_end"],
                "debt_to_equity": total_debt(r) / equity if equity else None,
                "current_ratio": (
                    assets / liabilities
                    if assets is not None and liabilities else None
                ),
            })
    for v in out.values():
        v.sort(key=lambda r: str(r["period_end"]))
    return out


def load_earnings_quality(tickers: list[str]) -> dict[str, dict]:
    """v1 reporting에 TTM quality view가 없으므로 값을 추정하지 않는다."""
    return {}


def load_shares_history(tickers: list[str]) -> dict[str, list[tuple[str, float]]]:
    """v1 share class snapshot은 아직 카드용 fan-out reader가 없다."""
    return {}


def load_valuation_snapshots(tickers: list[str]) -> dict[str, list[dict]]:
    """v1 선언에 valuation snapshot view가 없어 빈 이력을 유지한다."""
    return {}


# 카드가 축 embed를 그리는 데 필요한 세그먼트 컬럼.
# `secondary_axis`는 2차원(주 축×보조 축) 교차표 자식 행을 걸러 내려고 읽는다 —
# 카드는 아직 계층을 그리지 않고 1차원 축만 평평하게 나열한다. 표시용 이름과 이익
# 라벨은 저장하지 않고 member/profit_measure_kind에서 만든다.
_SEGMENT_CARD_COLUMNS = (
    "cik,accession_no,fiscal_year,fiscal_period,period_end,"
    "segment_type,axis,member,secondary_axis,segment_hash,is_derived,"
    "revenue,quality_status,coverage_ratio,"
    "profit_loss,profit_measure_kind,profit_quality_status,"
    "assets,assets_quality_status"
)


def load_segment_highlights(
    targets: set[tuple[str, str, int, str]],
) -> dict[tuple[str, str, int, str], dict]:
    """카드에 붙일 축별 세그먼트 상태를 만든다.

    전년 동기 비교가 필요해 대상 회계연도와 그 전년을 함께 읽는다. 공시 처리
    상태(`filing_processing`, content_type='segments')도 같이 넘긴다 — 아직 수집이
    안 끝난 공시를 '세그먼트 없음'으로 표시하면 안 되기 때문이다.
    """
    if not targets:
        return {}
    from investment_agent.reporting.notifications import earnings_report_segment_state as segment_state

    tickers = sorted({t[0] for t in targets})
    years = sorted({y for _, _, y, _ in targets} | {y - 1 for _, _, y, _ in targets})
    database = Database.from_config(load_config())
    securities = UniverseRepository(database).securities_by_ticker(tickers)
    ticker_by_cik = {
        str(security.cik): ticker
        for ticker, security in securities.items() if security.cik
    }
    if not ticker_by_cik:
        return {}
    rows = database.select_in_chunks(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_SEGMENT_METRICS,
        columns=_SEGMENT_CARD_COLUMNS,
        filter_column="cik",
        values=list(ticker_by_cik),
        configure=lambda query: query.in_("fiscal_year", years).is_("secondary_axis", "null"),
        order_by="cik,fiscal_year,fiscal_period,segment_hash",
    )
    # segment_state는 저장된 세그먼트 상태를 표시용 이름으로 변환한다.
    rows = [
        {
            **row,
            "ticker": ticker_by_cik.get(str(row.get("cik"))),
            "dimension_count": 1,
            "display_name": display_member_name(row.get("member")),
            "period_kind": "annual" if row.get("fiscal_period") == "FY" else "quarter",
        }
        for row in rows
        if ticker_by_cik.get(str(row.get("cik")))
    ]
    accessions = sorted({a for _, a, _, _ in targets})
    states: dict[tuple[str, str], dict] = {}
    if accessions:
        for state in database.select_in_chunks(
            schema=SCHEMA_FUNDAMENTALS,
            table=T_FILING_PROCESSING,
            columns="accession_no,status",
            filter_column="accession_no",
            values=accessions,
            configure=lambda query: query.eq("content_type", "segments"),
            order_by="accession_no,mapping_version",
        ):
            for ticker in tickers:
                states[(ticker, str(state["accession_no"]))] = state
    return segment_state.build(rows, targets, states)
