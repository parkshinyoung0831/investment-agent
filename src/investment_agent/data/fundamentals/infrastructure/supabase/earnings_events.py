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


def load_earnings_results(tickers: list[str] | None) -> list[dict[str, Any]]:
    """역사 예상치 재구성에 필요한 실적 속보 회계키만 읽는다."""
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
            .select("ticker,cik").in_("ticker", chunk),
            selected,
            order_by="ticker",
            paged_reader=select_all_paged,
        )
    else:
        securities = select_all_paged(
            lambda: sb.schema(SCHEMA_UNIVERSE).table(T_SECURITIES).select("ticker,cik"),
            order_by="ticker",
        )
    by_cik = {str(row["cik"]): str(row["ticker"]).upper() for row in securities if row.get("cik")}
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
            "ticker": by_cik.get(str(row.get("cik"))),
            "filed_at": filed_by_accession.get(str(row.get("accession_no"))),
        }
        for row in results
        if filed_by_accession.get(str(row.get("accession_no")))
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
            "report_date": row.get("period_end"),
            "source": row.get("source") or "sec_edgar",
        }
        for row in rows
        if row.get("accession_no") and row.get("cik") and row.get("filed_at")
    ]
    if filings:
        sb.schema(_SCHEMA).table(T_FILINGS).upsert(filings, on_conflict="accession_no").execute()
    # `accession_no`는 PK의 일부이자 filings FK다. 투영에서 빠지면 NOT NULL 위반으로
    # 그 종목의 속보가 통째로 저장되지 않는다 — 실측 27종목이 그렇게 실패했다
    # (AVGO·CRM·CRWD·DELL 등). on_conflict가 그 이름을 부르고 있는데 payload에는
    # 없다는 것이 곧 모순이고, 아래 테스트가 그 모순을 잡는다.
    payload_keys = {
        "cik", "accession_no", "fiscal_year", "fiscal_period", "period_end",
        "revenue_actual", "eps_actual", "operating_income_actual", "net_income_actual",
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
