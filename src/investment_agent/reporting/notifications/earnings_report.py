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
T_SHARE_CLASS_SNAPSHOTS = "share_class_snapshots"
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
    "common_dividends_paid,shares_fully_diluted_average,shares_average,mapping_version,"
    # 손익 구조의 매출총이익·세전이익, 현금흐름 브릿지의 감가상각·주식보상,
    # 유동성 차트의 유동자산/유동부채, 운전자본 회전의 매출채권·재고·매입채무,
    # Altman Z의 이익잉여금. 전부 financials가 선언·적재하고 있는데 읽지 않아
    # 카드에서 빈칸이나 $0으로 나왔다.
    "gross_profit,cost_of_goods_and_services_sold,pretax_income_loss,income_taxes,"
    "interest_expense,current_assets_total,current_liabilities_total,"
    "depreciation_amortization_cf,stock_based_compensation_cf,"
    "trade_receivables,inventories,trade_payables,retained_earnings"
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


# ── 카드가 쓰는 파생 read model ────────────────────────────────────────────
#
# 아래 다섯은 한동안 빈 값을 그대로 돌려주고 있었다("v1에 view가 없다"). 그런데
# 필요한 사실은 전부 fundamentals.financials와 share_class_snapshots에 이미
# 적재돼 있다 — 없던 것은 뷰가 아니라 그 사실을 접는 코드였다. 뷰를 새로 만들지
# 않는 이유는 계산 규칙이 카드의 표시 규칙과 함께 움직이기 때문이다. DB에 굳혀
# 두면 규칙이 바뀔 때 과거 행이 조용히 옛 규칙을 말한다(market이 조정가를 저장하지
# 않는 것과 같은 이유).

def _quarterly_by_ticker(tickers: list[str]) -> dict[str, list[dict]]:
    """티커별 분기 행을 기간 오름차순으로 모은다."""
    out: dict[str, list[dict]] = {}
    for row in _financial_rows(tickers):
        if row.get("fiscal_period") not in QUARTERS or not row.get("period_end"):
            continue
        out.setdefault(str(row["ticker"]), []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: str(r.get("period_end") or ""))
    return out


def _ttm(rows: list[dict], column: str) -> float | None:
    """직전 4분기 합. 한 분기라도 비면 TTM을 만들지 않는다 — 부분 합은 틀린 값이다."""
    window = rows[-4:]
    if len(window) < 4:
        return None
    values = [f(row.get(column)) for row in window]
    return None if any(value is None for value in values) else float(sum(values))


def _net_debt(row: dict) -> float | None:
    debt = total_debt(row)
    cash = f(row.get("cash_and_cash_equivalents"))
    if debt is None or cash is None:
        return None
    return debt - cash


def _ev_ex_market_cap(row: dict) -> float | None:
    """EV = 시총 + 이 값. 순부채에 소수주주 지분과 우선주를 더한다."""
    net = _net_debt(row)
    if net is None:
        return None
    for column in ("minority_interest_balance", "preferred_stock"):
        net += f(row.get(column)) or 0.0
    return net


def _ebitda_ttm(rows: list[dict]) -> float | None:
    operating = _ttm(rows, "operating_income_loss")
    if operating is None:
        return None
    return operating + (_ttm(rows, "depreciation_amortization_cf") or 0.0)


def _fcf_ttm(rows: list[dict]) -> float | None:
    operating = _ttm(rows, "net_cash_from_operating_activities")
    capex = _ttm(rows, "capital_expenses")
    if operating is None or capex is None:
        return None
    return operating - abs(capex)


def load_valuation_snapshots(tickers: list[str]) -> dict[str, list[dict]]:
    """역사 밸류에이션이 각 거래일에 붙일 "그날 공개돼 있던 재무" 스냅샷.

    available_date는 공시 접수일이다 — 그보다 이른 거래일에 이 분기 숫자를 쓰면
    미래를 본 밸류에이션이 된다.
    """
    out: dict[str, list[dict]] = {}
    for ticker, rows in _quarterly_by_ticker(tickers).items():
        snapshots: list[dict] = []
        for end in range(4, len(rows) + 1):
            window = rows[:end]
            current = window[-1]
            available = str(current.get("filed_at") or current.get("source_filing_date") or "")
            if not available:
                continue
            snapshots.append({
                "available_date": available[:10],
                "earnings_ttm": _ttm(window, "net_income"),
                "revenue_ttm": _ttm(window, "revenue"),
                "ebitda_ttm": _ebitda_ttm(window),
                "book_value": f(current.get("common_equity")),
                "ev_ex_market_cap": _ev_ex_market_cap(current),
                "fcf_ttm": _fcf_ttm(window),
            })
        snapshots.sort(key=lambda snapshot: snapshot["available_date"])
        if snapshots:
            out[ticker] = snapshots
    return out


def load_shares_history(tickers: list[str]) -> dict[str, list[tuple[str, float]]]:
    """발행주식수 이력. 같은 날 여러 종류주가 있으면 합쳐 한 점으로 만든다."""
    if not tickers:
        return {}
    database = Database.from_config(load_config())
    securities = UniverseRepository(database).securities_by_ticker(tickers)
    by_cik = {
        str(security.cik): ticker
        for ticker, security in securities.items() if security.cik
    }
    if not by_cik:
        return {}
    rows = database.select_in_chunks(
        schema=SCHEMA_FUNDAMENTALS,
        table=T_SHARE_CLASS_SNAPSHOTS,
        columns="cik,as_of_date,shares_outstanding",
        filter_column="cik",
        values=list(by_cik),
        order_by="cik,as_of_date",
    )
    totals: dict[str, dict[str, float]] = {}
    for row in rows:
        ticker = by_cik.get(str(row.get("cik") or ""))
        shares = f(row.get("shares_outstanding"))
        as_of = str(row.get("as_of_date") or "")[:10]
        if not ticker or shares is None or not as_of:
            continue
        totals.setdefault(ticker, {})
        totals[ticker][as_of] = totals[ticker].get(as_of, 0.0) + shares
    return {ticker: sorted(points.items()) for ticker, points in totals.items() if points}


def load_valuation(tickers: list[str]) -> dict[str, dict]:
    """카드 머리의 주가·시총·EV. 역사 스냅샷의 마지막 점과 같은 규칙으로 만든다.

    기준 시점은 공시 접수일이다. 그날 종가와 그날까지 공개돼 있던 발행주식수를
    곱해야 카드의 다른 값들과 같은 시점을 말한다 — 오늘 종가를 쓰면 몇 달 지난
    공시의 카드가 오늘 시총을 주장하게 된다.
    """
    snapshots_by_ticker = load_valuation_snapshots(tickers)
    if not snapshots_by_ticker:
        return {}
    prices = load_price_history(list(snapshots_by_ticker))
    shares = load_shares_history(list(snapshots_by_ticker))
    out: dict[str, dict] = {}
    for ticker, snapshots in snapshots_by_ticker.items():
        latest = dict(snapshots[-1])
        as_of = str(latest.get("available_date") or "")
        # 공시 당일의 반응은 배제한다 — 카드의 주가 블록(prices_before_filing)과
        # 같은 기준이어야 머리의 시총과 아래 주가가 같은 날을 말한다.
        close = _as_of_value(
            [(str(row["trade_date"]), f(row.get("close")))
             for row in prices.get(ticker, []) if row.get("close") is not None],
            as_of,
            strictly_before=True,
        )
        count = _as_of_value(shares.get(ticker, []), as_of)
        latest["price"] = close
        latest["market_cap"] = None if close is None or count is None else close * count
        latest["enterprise_value"] = (
            None if latest["market_cap"] is None or latest.get("ev_ex_market_cap") is None
            else latest["market_cap"] + latest["ev_ex_market_cap"]
        )
        out[ticker] = latest
    return out


def _as_of_value(
    points: list[tuple[str, float | None]],
    as_of: str,
    *,
    strictly_before: bool = False,
) -> float | None:
    """as_of 시점에 유효한 마지막 값. 없으면 None.

    입력 정렬을 가정하지 않는다 — 조회 경로마다 정렬이 다르고, 정렬을 가정한
    조기 종료는 값을 조용히 엉뚱한 날짜로 만든다.
    """
    usable = [
        (str(when)[:10], float(value))
        for when, value in points
        if value is not None and (
            str(when)[:10] < as_of if strictly_before else str(when)[:10] <= as_of
        )
    ]
    return max(usable)[1] if usable else None


def load_earnings_quality(tickers: list[str]) -> dict[str, dict]:
    """이익의 질(TTM) — OCF/순이익·FCF/순이익·발생액.

    발생액은 (순이익 − 영업현금흐름) / 총자산이다. 이익이 현금으로 뒷받침되는지
    보는 값이라 분모는 매출이 아니라 자산이다.
    """
    out: dict[str, dict] = {}
    for ticker, rows in _quarterly_by_ticker(tickers).items():
        net_income = _ttm(rows, "net_income")
        operating = _ttm(rows, "net_cash_from_operating_activities")
        if net_income is None or operating is None:
            continue
        assets = f(rows[-1].get("assets"))
        out[ticker] = {
            "net_income_ttm": net_income,
            "operating_cash_flow_ttm": operating,
            "free_cash_flow_ttm": _fcf_ttm(rows),
            "accruals_ttm": None if not assets else (net_income - operating) / assets,
        }
    return out


def _altman_z(row: dict, *, operating_ttm: float | None) -> float | None:
    """Altman Z''(비제조·신흥시장형). 제조업 전용 Z와 달리 매출/자산 항이 없다.

    Z'' = 6.56·(운전자본/자산) + 3.26·(이익잉여금/자산)
        + 6.72·(영업이익/자산) + 1.05·(자본/부채)
    """
    assets = f(row.get("assets"))
    liabilities = f(row.get("liabilities"))
    if not assets or not liabilities:
        return None
    parts = [
        f(row.get("current_assets_total")),
        f(row.get("current_liabilities_total")),
        f(row.get("retained_earnings")),
        # EBIT은 TTM이다. 분기 영업이익을 연간 자산과 견주면 항이 1/4로 줄어
        # 우량 기업이 위험 구간으로 내려앉는다.
        operating_ttm,
        f(row.get("common_equity")),
    ]
    if any(part is None for part in parts):
        return None
    current_assets, current_liabilities, retained, operating, equity = parts
    return (
        6.56 * ((current_assets - current_liabilities) / assets)
        + 3.26 * (retained / assets)
        + 6.72 * (operating / assets)
        + 1.05 * (equity / liabilities)
    )


def load_health(tickers: list[str]) -> dict[str, dict]:
    """수익성·자본효율과 재무건전성 게이지.

    분모는 기말 잔액이다. 평균 잔액이 이론적으로는 낫지만, 이 카드의 다른 값들과
    같은 시점을 말해야 "이번 분기의 상태"로 읽힌다.
    """
    out: dict[str, dict] = {}
    for ticker, rows in _quarterly_by_ticker(tickers).items():
        net_income = _ttm(rows, "net_income")
        if net_income is None:
            continue
        current = rows[-1]
        equity = f(current.get("common_equity"))
        assets = f(current.get("assets"))
        debt = total_debt(current)
        invested = None if equity is None else equity + (debt or 0.0)
        ebitda = _ebitda_ttm(rows)
        net_debt = _net_debt(current)
        interest = _ttm(rows, "interest_expense")
        operating = _ttm(rows, "operating_income_loss")

        health = {
            "roe": None if not equity else net_income / equity,
            "roa": None if not assets else net_income / assets,
            "roic": None if not invested else net_income / invested,
            "interest_coverage": (
                None if not interest or operating is None else operating / abs(interest)
            ),
            "net_debt_to_ebitda": (
                None if not ebitda or net_debt is None else net_debt / ebitda
            ),
            "altman_z": _altman_z(current, operating_ttm=operating),
        }
        if any(value is not None for value in health.values()):
            out[ticker] = health
    return out
