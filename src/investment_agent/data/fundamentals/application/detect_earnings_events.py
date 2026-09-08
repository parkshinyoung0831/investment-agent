"""8-K Item 2.02를 감지해 실적 속보를 만든다."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from investment_agent.platform.clock import us_market_today
from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.application.earnings_results import (
    build_earnings_results,
)
from investment_agent.data.fundamentals.application import (
    EarningsEventRepository,
    EarningsFilingSource,
    PressReleaseDocument,
    PressReleaseSource,
    ReportedEarningsSource,
)
from investment_agent.data.fundamentals.domain.services.match_reported_earnings import (
    match_reported_earnings,
)

log = get_logger(__name__)

def reported_eps_for_filing(
    reported_earnings: dict[str, dict[str, float | None]],
    filed_at: str,
) -> float | None:
    """8-K 접수일과 같은 발표의 조정 EPS 실제값만 고른다.

    Yahoo 발표일과 SEC 접수일은 보통 같지만, 장 마감 뒤 제출은 다음 영업일로
    밀릴 수 있다. 세 달 뒤 다른 분기가 섞이지 않도록 3일 안의 가장 가까운 값만
    허용한다.
    """
    matched = match_reported_earnings(reported_earnings, filed_at)
    if matched is None:
        return None
    return matched[1].get("eps_actual")


def determine_fiscal_period(
    ticker: str,
    filing_date: str,
    report_date: str,
    *,
    repository: EarningsEventRepository | None = None,
) -> tuple[int, str, str] | None:
    """8-K 공시일을 회사의 실제 회계분기에 붙인다.

    회계력을 못 읽거나 정상 범위를 벗어나면 **추정하지 않고 None**을 돌려준다.
    회사별 회계력에 근거하지 못하는 발표는 속보로 보내지 않는다.
    """
    from investment_agent.data.fundamentals.domain.services.resolve_flash_period import (
        resolve_flash_period,
    )

    if repository is None or not hasattr(repository, "load_fiscal_calendar"):
        return None
    calendar = repository.load_fiscal_calendar(ticker)
    resolved = resolve_flash_period(calendar, filing_date)
    if resolved is None:
        log.warning(
            "earnings flash: %s 회계분기 판정 실패 filed=%s report=%s "
            "(회계력 %d분기) — 이 속보는 건너뛴다",
            ticker, filing_date, report_date, len(calendar),
        )
    return resolved


def detect_earnings_events_for_ticker(
    ticker: str,
    cik: str,
    *,
    filing_source: EarningsFilingSource,
    press_release_source: PressReleaseSource,
    repository: EarningsEventRepository,
    reported_source: ReportedEarningsSource | None = None,
    cutoff_days: int = 14,
    today: date | None = None,
) -> dict:
    """한 종목의 최근 실적 8-K를 찾아 멱등 저장한다."""
    if cutoff_days < 1:
        raise ValueError("cutoff_days must be at least 1")
    today = today or us_market_today()
    filings = filing_source.earnings_8k_filings(
        cik,
        cutoff=today - timedelta(days=cutoff_days),
    )
    reported_earnings: dict[str, dict[str, float | None]] = {}
    failures: list[dict[str, str]] = []
    if filings and reported_source is not None:
        try:
            reported_earnings = reported_source.fetch_reported_earnings(ticker)
        except Exception as exc:
            log.warning("earnings flash: %s Yahoo EPS 조회 실패", ticker, exc_info=True)
            failures.append({
                "ticker": ticker,
                "stage": "reported_earnings",
                "error": repr(exc),
            })
    records: list[dict] = []
    skipped = 0
    for filing in filings:
        resolved = determine_fiscal_period(
            ticker,
            filing.filing_date,
            filing.report_date,
            repository=repository,
        )
        if resolved is None:
            skipped += 1
            continue
        fiscal_year, fiscal_period, period_end = resolved
        release_document = press_release_source.press_release_document(
            cik,
            filing.accession_no,
            filing.primary_document,
        )
        if isinstance(release_document, PressReleaseDocument):
            html = release_document.html
            press_release_url = release_document.url
            parsed_revenue_actual = release_document.revenue_actual
            operating_income_actual = release_document.operating_income_actual
            net_income_actual = release_document.net_income_actual
            guidance_summary = release_document.guidance_summary
            if parsed_revenue_actual is None or guidance_summary is None:
                fallback_revenue, fallback_guidance = _parse_release_html(html)
                parsed_revenue_actual = parsed_revenue_actual or fallback_revenue
                guidance_summary = guidance_summary or fallback_guidance
        else:
            raise TypeError("press_release_document must return PressReleaseDocument")
        revenue_actual = parsed_revenue_actual
        records.append(
            build_earnings_results(
                cik=cik,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                period_end=period_end,
                filed_at=filing.filing_date,
                accession_no=filing.accession_no,
                form_type=getattr(filing, "form_type", "8-K"),
                report_date=getattr(filing, "report_date", None),
                revenue_actual=revenue_actual,
                eps_actual=reported_eps_for_filing(
                    reported_earnings,
                    filing.filing_date,
                ),
                operating_income_actual=operating_income_actual,
                net_income_actual=net_income_actual,
                guidance_summary=guidance_summary,
                press_release_url=press_release_url,
            )
        )

    row_count = repository.upsert_earnings_results(records)
    return {
        "ticker": ticker,
        "filings_discovered": len(filings),
        "period_unresolved": skipped,
        "rows": row_count,
        "records": records,
        "failures": failures,
    }


def _parse_release_html(html_content: str | bytes | None) -> tuple[float | None, str | None]:
    """구조화 결과가 없는 보도자료 HTML에서 누락 필드를 보완한다."""
    from investment_agent.data.fundamentals.domain.services.parse_earnings_release import (
        parse_earnings_release,
    )

    return parse_earnings_release(html_content)


def detect_earnings_events(
    targets: list[tuple[str, str]],
    *,
    filing_source: EarningsFilingSource,
    press_release_source: PressReleaseSource,
    repository: EarningsEventRepository,
    reported_source: Any = None,
    cutoff_days: int = 14,
    today: date | None = None,
) -> dict:
    """여러 종목을 독립적으로 처리해 한 종목 실패가 전체를 막지 않게 한다."""
    metrics = {
        "tickers": len(targets),
        "tickers_processed": 0,
        "filings_discovered": 0,
        "rows": 0,
        "failures": [],
    }
    for ticker, cik in targets:
        try:
            result = detect_earnings_events_for_ticker(
                ticker,
                cik,
                filing_source=filing_source,
                press_release_source=press_release_source,
                repository=repository,
                reported_source=reported_source,
                cutoff_days=cutoff_days,
                today=today,
            )
            metrics["tickers_processed"] += 1
            metrics["filings_discovered"] += result["filings_discovered"]
            metrics["rows"] += result["rows"]
            metrics["failures"].extend(result.get("failures") or [])
        except Exception as exc:  # noqa: BLE001 - 다른 종목은 계속한다
            log.warning("earnings event failed ticker=%s error=%r", ticker, exc)
            metrics["failures"].append({"ticker": ticker, "error": repr(exc)})
    return metrics


