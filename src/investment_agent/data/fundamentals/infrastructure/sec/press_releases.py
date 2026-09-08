"""SEC archive에서 8-K 실적 보도자료와 요약 재무값을 읽는 어댑터."""
from __future__ import annotations

from investment_agent.data.universe.infrastructure.sources import sec
from investment_agent.data.fundamentals.application.market_sources import PressReleaseDocument
from investment_agent.data.fundamentals.infrastructure.sec.edgar_parser import (
    exhibit_extractor,
    table_parser,
)


def _selected_name(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or "").strip()
    return str(getattr(item, "name", "") or "").strip()


def _decode_html(payload: bytes) -> str:
    """SEC 문서의 흔한 인코딩을 숫자 손실 없이 문자열로 바꾼다."""
    for encoding in ("utf-8", "windows-1252", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def press_release_document(
    cik: str | int,
    accession_no: str,
    primary_document: str | None,
) -> PressReleaseDocument:
    """SEC archive 목록에서 EX-99 보도자료를 선택해 HTML과 실제값을 반환한다."""
    archive_items = sec.filing_archive_items(cik, accession_no)
    selected = exhibit_extractor.select_exhibit(archive_items, primary_document)
    filename = _selected_name(selected) if selected is not None else ""
    # 첨부 설명이 없는 공시는 primary document가 유일한 HTML일 수 있다.
    if not filename and primary_document:
        filename = str(primary_document).strip()
    if not filename:
        return PressReleaseDocument(html=None, url=None)
    url = sec.filing_document_url(cik, accession_no, filename)
    payload = sec.get_bytes_optional(url)
    if payload is None:
        return PressReleaseDocument(html=None, url=url)
    html = _decode_html(payload)
    financials = table_parser.extract_summary_financials(html)
    return PressReleaseDocument(
        html=html,
        url=url,
        revenue_actual=financials.get("revenue"),
        operating_income_actual=financials.get("operating_income"),
        net_income_actual=financials.get("net_income"),
        guidance_summary=exhibit_extractor.extract_guidance_text(html),
    )
