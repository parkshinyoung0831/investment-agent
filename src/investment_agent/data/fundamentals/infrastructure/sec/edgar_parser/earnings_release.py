"""8-K 실적 발표에서 저장 가능한 요약값을 조립한다."""
from __future__ import annotations

from .exhibit_extractor import extract_guidance_text
from .table_parser import extract_summary_financials


def parse_8k_earnings(html_content: str | bytes | object | None) -> dict[str, float | str | None]:
    """내재화한 표·본문 파서로 8-K 실적값을 한 번에 추출한다."""
    financials = extract_summary_financials(html_content)
    return {
        "revenue_actual": financials.get("revenue"),
        "operating_income_actual": financials.get("operating_income"),
        "net_income_actual": financials.get("net_income"),
        "guidance_summary": extract_guidance_text(html_content),
    }
