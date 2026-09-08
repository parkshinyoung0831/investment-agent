"""8-K Item 번호를 외부 SDK 없이 분류한다."""
from __future__ import annotations

import re
from collections.abc import Iterable

from bs4 import BeautifulSoup

_ITEM_RE = re.compile(r"(?<![\d.])(?:item\s*)?(\d{1,2}\.\d{2})(?![\d.])", re.IGNORECASE)
_EARNINGS_ITEM = "2.02"


def extract_item_numbers(value: str | Iterable[str] | None) -> tuple[str, ...]:
    """SEC metadata나 HTML 텍스트에서 중복 없는 Item 번호를 순서대로 뽑는다."""
    if value is None:
        return ()
    if isinstance(value, str):
        text = value
    else:
        text = " ".join(str(part) for part in value)
    found: list[str] = []
    for match in _ITEM_RE.finditer(text):
        item = match.group(1)
        if item not in found:
            found.append(item)
    return tuple(found)


def classify_8k_items(
    form_type: str,
    items: str | Iterable[str] | None = None,
    *,
    html: str | None = None,
) -> str:
    """8-K를 실적·임원변동·기타 중 하나로 분류한다."""
    form = str(form_type or "").strip().upper()
    if form != "8-K":
        return "other"
    source = items
    if source is None and html:
        source = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    item_numbers = set(extract_item_numbers(source))
    if not item_numbers and html and source is not html:
        # submissions 메타데이터가 비어도 본문 헤더의 Item 번호로 보완한다.
        item_numbers = set(extract_item_numbers(html))
    if _EARNINGS_ITEM in item_numbers:
        return "earnings"
    if "5.02" in item_numbers:
        return "executive_change"
    return "other"


def is_earnings_item(
    form_type: str,
    items: str | Iterable[str] | None = None,
    *,
    html: str | None = None,
) -> bool:
    """최초 Form 8-K의 Item 2.02인지 반환한다."""
    return classify_8k_items(form_type, items, html=html) == "earnings"


__all__ = [
    "classify_8k_items",
    "extract_item_numbers",
    "is_earnings_item",
]
