"""실적 발표 관측값을 earnings_results 저장 행으로 투영한다."""
from __future__ import annotations

from typing import Any


def build_earnings_results(
    *,
    cik: str,
    fiscal_year: int,
    fiscal_period: str,
    period_end: str,
    filed_at: str,
    accession_no: str,
    form_type: str = "8-K",
    report_date: str | None = None,
    revenue_actual: float | None = None,
    eps_actual: float | None = None,
    operating_income_actual: float | None = None,
    net_income_actual: float | None = None,
    guidance_summary: str | None = None,
    press_release_url: str | None = None,
    source: str = "sec_8k",
) -> dict[str, Any]:
    """실적 속보 테이블의 단일 행을 명시적인 필드로 만든다.

    예상치는 담지 않는다. 서프라이즈는 ``reporting.earnings_surprise``가
    ``earnings_estimates``를 ``snapshot_date < filed_at``으로 조인해 발표 시점
    기준으로 계산한다. 결과 행에 복제하지 않아 컨센서스 갱신에도 과거 값이 흔들리지 않는다.
    """
    if fiscal_period not in {"Q1", "Q2", "Q3", "Q4", "FY"}:
        raise ValueError(f"unsupported fiscal period: {fiscal_period}")
    normalized_cik = str(cik).zfill(10)
    if len(normalized_cik) != 10 or not normalized_cik.isdigit():
        raise ValueError(f"invalid CIK: {cik!r}")
    return {
        "cik": normalized_cik,
        "fiscal_year": int(fiscal_year),
        "fiscal_period": fiscal_period,
        "period_end": period_end,
        "filed_at": filed_at,
        "accession_no": accession_no,
        "form_type": form_type,
        "report_date": report_date or period_end,
        "revenue_actual": revenue_actual,
        "eps_actual": eps_actual,
        "operating_income_actual": operating_income_actual,
        "net_income_actual": net_income_actual,
        "guidance_summary": guidance_summary,
        "press_release_url": press_release_url,
        "source": source,
    }

