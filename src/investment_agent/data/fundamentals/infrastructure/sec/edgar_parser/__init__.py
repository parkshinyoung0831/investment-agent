"""SEC 8-K 보도자료에서 필요한 값만 읽는 경량 파서 묶음.

이 패키지는 외부 EDGAR SDK를 호출하지 않는다. SEC archive에서 받은 HTML과 파일
목록만 받아 순수하게 분류·정제·표 추출을 수행한다.
"""
from __future__ import annotations

from .exhibit_extractor import (
    clean_html_to_markdown,
    extract_guidance_text,
    extract_text,
    select_exhibit,
)
from .item_classifier import (
    classify_8k_items,
    extract_item_numbers,
    is_earnings_item,
)
from .table_parser import extract_summary_financials, normalize_table
from .earnings_release import parse_8k_earnings

__all__ = [
    "classify_8k_items",
    "clean_html_to_markdown",
    "extract_guidance_text",
    "extract_item_numbers",
    "extract_summary_financials",
    "extract_text",
    "is_earnings_item",
    "normalize_table",
    "parse_8k_earnings",
    "select_exhibit",
]
