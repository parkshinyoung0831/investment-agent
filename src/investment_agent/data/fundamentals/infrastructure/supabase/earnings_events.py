"""실적 발표 속보 저장을 담당하는 저장소."""
from __future__ import annotations

from typing import Any

from investment_agent.platform.db.postgres import sb, select_all_paged, select_paged_in_chunks

# --- DB 식별자 (SSOT) ---------------------------------------------------
T_EARNINGS_RESULTS = "earnings_results"
T_FILINGS = "filings"
T_SECURITIES = "securities"
T_FINANCIALS = "financials"
SCHEMA_UNIVERSE = "universe"
# ----------------------------------------------------------------------


_SCHEMA = "fundamentals"


def load_fiscal_calendar(ticker: str) -> list[dict[str, Any]]:
    """종목의 실제 회계력. 8-K를 올바른 회계분기에 붙이는 유일한 근거다.

    달력 월로 분기를 매기면 1월 결산 유통사가 통째로 어긋난다 —
    WMT가 2026-08-20에 낸 8-K는 FY2027 Q2(2026-07-31 종료)이지 FY2026 Q3가 아니다.
    """
    from investment_agent.data.fundamentals.infrastructure.supabase import expectations

    return expectations.fiscal_periods([ticker])


def tracked_tickers_by_cik(securities: list[dict[str, Any]]) -> dict[str, list[str]]:
    """수집 게이트를 지난 종목만 CIK별 ticker 목록으로 묶는다.

    같은 CIK에는 우선주·채권·자리표시 종목도 있다. 그 ticker로 예상치를 만들면 보통주의
    서프라이즈에 붙지 않는다. 의결권이 다른 보통주(GOOG/GOOGL)는 둘 다 남긴다.
    """
    out: dict[str, set[str]] = {}
    for row in securities:
        cik, ticker = str(row.get("cik") or ""), str(row.get("ticker") or "").upper()
        if cik and ticker and row.get("is_tracked") and row.get("security_type") == "common_stock":
            out.setdefault(cik, set()).add(ticker)
    return {cik: sorted(tickers) for cik, tickers in out.items()}


def load_earnings_results(tickers: list[str] | None) -> list[dict[str, Any]]:
    """역사 예상치 재구성에 필요한 실적 속보 회계키만 읽는다. 행은 수집 대상 보통주마다 하나다."""
    selected = (
        sorted({str(ticker).upper() for ticker in tickers if str(ticker).strip()})
        if tickers is not None
        else None
    )
    if selected == []:
        return []

    if selected:
        securities = select_paged_in_chunks(
            lambda chunk: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
            .select("ticker,cik,security_type,is_tracked").in_("ticker", chunk),
            selected,
            order_by="ticker",
            paged_reader=select_all_paged,
        )
    else:
        securities = select_all_paged(
            lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES)
            .select("ticker,cik,security_type,is_tracked").eq("is_tracked", True),
            order_by="ticker",
        )
    by_cik = tracked_tickers_by_cik(securities)
    if not by_cik:
        return []
    results = select_paged_in_chunks(
        lambda chunk: sb.schema(_SCHEMA).table(T_EARNINGS_RESULTS)
        .select("*").in_("cik", chunk),
        sorted(by_cik),
        order_by="cik,period_end,accession_no",
        paged_reader=select_all_paged,
    )
    accessions = sorted({str(row["accession_no"]) for row in results if row.get("accession_no")})
    filings = select_paged_in_chunks(
        lambda chunk: sb.schema(_SCHEMA).table(T_FILINGS)
        .select("accession_no,filing_date").in_("accession_no", chunk),
        accessions,
        order_by="accession_no",
        paged_reader=select_all_paged,
    ) if accessions else []
    filed_by_accession = {str(row["accession_no"]): row.get("filing_date") for row in filings}
    return [
        {
            **row,
            "ticker": ticker,
            "filed_at": filed_by_accession.get(str(row.get("accession_no"))),
        }
        for row in results
        if filed_by_accession.get(str(row.get("accession_no")))
        for ticker in by_cik.get(str(row.get("cik")), [])
    ]


def upsert_earnings_results(rows: list[dict[str, Any]]) -> int:
    """실적 속보 행을 자연키 기준으로 멱등 저장한다."""
    if not rows:
        return 0
    filings = [
        {
            "accession_no": row["accession_no"],
            "cik": str(row["cik"]).zfill(10),
            "form_type": row.get("form_type") or "8-K",
            "filing_date": row.get("filed_at"),
            "report_date": row.get("report_date"),
            "source": row.get("source") or "sec_edgar",
        }
        for row in rows
        if row.get("accession_no") and row.get("cik") and row.get("filed_at")
    ]
    if filings:
        # 공시 행의 주인은 공시 경로다. 여기서는 FK 부모가 없을 때만 만든다.
        sb.schema(_SCHEMA).table(T_FILINGS).upsert(
            filings, on_conflict="accession_no", ignore_duplicates=True
        ).execute()
    # `accession_no`는 PK의 일부이자 filings FK다. 투영에서 빠지면 NOT NULL 위반으로
    # 그 종목의 속보가 통째로 저장되지 않는다 — 실측 27종목이 그렇게 실패했다
    # (AVGO·CRM·CRWD·DELL 등). on_conflict가 그 이름을 부르고 있는데 payload에는
    # 없다는 것이 곧 모순이고, 아래 테스트가 그 모순을 잡는다.
    payload_keys = {
        "cik", "accession_no", "fiscal_year", "fiscal_period", "period_end",
        "revenue_actual", "eps_actual", "eps_basis", "operating_income_actual", "net_income_actual",
        "guidance_summary", "press_release_url", "source",
    }
    payload = [{key: value for key, value in row.items() if key in payload_keys} for row in rows]
    response = sb.schema(_SCHEMA).table(T_EARNINGS_RESULTS).upsert(
        payload, on_conflict="cik,fiscal_year,fiscal_period,accession_no"
    ).execute()
    return len(response.data or payload)


__all__ = [
    "load_earnings_results",
    "load_fiscal_calendar",
    "upsert_earnings_results",
]
