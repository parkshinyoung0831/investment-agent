"""실적 보도자료 HTML에서 실제 매출과 가이던스 문장을 추출한다."""
from __future__ import annotations

import re

_REVENUE_PATTERN = re.compile(
    r"(?:total\s+|net\s+)?revenue(?:s)?"
    r"(?:\s+(?!\$)[a-z-]+){0,8}\s*(?:of|was|were)?\s*"
    r"\$([\d\.,]+)\s*(billion|million|b|m)",
    re.IGNORECASE,
)
_TABLE_REVENUE_LABELS = frozenset({
    "revenue",
    "total revenue",
    "total revenues",
    "net revenue",
    "net revenues",
    "total net revenue",
    "total net revenues",
    "sales",
    "total sales",
    "net sales",
})
_TABLE_GUIDANCE_TERMS = ("guidance", "outlook", "expected", "forecast")
_TABLE_QUARTERLY_TERMS = ("quarter", "three months", "13 weeks", "14 weeks")
_TABLE_CUMULATIVE_TERMS = ("full year", "fiscal year", "year ended", "nine months", "six months")
_GUIDANCE_TERMS = (
    "raises full year",
    "guidance",
    "full-year outlook",
    "fiscal outlook",
)


def _normalize_text(value: str) -> str:
    """HTML에서 읽은 공백과 글머리표를 비교 가능한 한 줄로 정리한다."""
    return " ".join(
        value.replace("\u2022", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\xa0", " ")
        .split()
    )


def _normalized_label(value: str) -> str:
    """표 행의 각주·기호를 빼고 허용한 매출 레이블과 비교한다."""
    return " ".join(re.sub(r"[^a-z]+", " ", value.lower()).split())


def _table_multiplier(table) -> float:
    """표 안이나 가까운 제목의 표시 단위를 달러 원단위 배수로 바꾼다."""
    context_parts = [table.get_text(" ", strip=True)]
    for previous in table.find_all_previous(("caption", "p", "div"), limit=3):
        context_parts.append(previous.get_text(" ", strip=True))
    context = " ".join(context_parts).lower()
    if "$000" in context or "$ 000" in context or "(000" in context:
        return 1e3
    if "in billions" in context or "in billions of dollars" in context:
        return 1e9
    if "in thousands" in context or "in thousands of dollars" in context:
        return 1e3
    if "in millions" in context or "in millions of dollars" in context:
        return 1e6
    return 1.0


def _first_table_amount(cells) -> float | None:
    """행의 실제 현재기간 금액(첫 숫자)을 안전하게 읽는다."""
    for cell in cells:
        text = _normalize_text(cell.get_text(" ", strip=True))
        if "%" in text or " to " in text.lower():
            continue
        match = re.search(r"\$?\s*\(?([\d][\d,]*(?:\.\d+)?)\)?", text)
        if match:
            value = float(match.group(1).replace(",", ""))
            return -value if "(" in text and ")" in text else value
    return None


def _html_table_priority(table) -> int:
    """현재 분기 표를 연간·누적 표보다 먼저 읽는다."""
    text = _normalize_text(table.get_text(" ", strip=True)).lower()
    if any(term in text for term in _TABLE_QUARTERLY_TERMS):
        return 2
    if any(term in text for term in _TABLE_CUMULATIVE_TERMS):
        return 0
    return 1


def _revenue_from_tables(soup) -> float | None:
    """EDGARTools가 표를 만들지 못한 EX-99에서 전사 분기 매출 행을 보완한다."""
    candidates: list[tuple[int, float]] = []
    for table_index, table in enumerate(soup.find_all("table")):
        table_text = _normalize_text(table.get_text(" ", strip=True)).lower()
        if any(term in table_text for term in _TABLE_GUIDANCE_TERMS):
            continue
        multiplier = _table_multiplier(table)
        for row in table.find_all("tr"):
            cells = row.find_all(("th", "td"), recursive=False)
            if len(cells) < 2:
                continue
            label = _normalized_label(cells[0].get_text(" ", strip=True))
            if label not in _TABLE_REVENUE_LABELS:
                continue
            amount = _first_table_amount(cells[1:])
            if amount is not None and amount > 0:
                candidates.append((
                    _html_table_priority(table),
                    -table_index,
                    amount * multiplier,
                ))
    return max(candidates)[2] if candidates else None


def parse_earnings_release(html: str | bytes | None) -> tuple[float | None, str | None]:
    """보도자료에서 ``(revenue_actual, guidance_summary)``를 반환한다.

    통화 단위가 명시된 headline 매출을 우선 읽고, 그 값이 없을 때만 EX-99의 전사
    손익표를 보완한다. 가이던스는 원문의 의미를 바꾸지 않고 최대 두 문장까지
    연결하며, 내용이 없거나 파싱할 수 없으면 각각 ``None``을 반환한다.
    """
    if not html:
        return None, None

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    document_text = _normalize_text(soup.get_text(" ", strip=True))

    revenue_actual = _revenue_from_tables(soup)
    match = _REVENUE_PATTERN.search(document_text)
    if revenue_actual is None and match:
        value = float(match.group(1).replace(",", ""))
        multiplier = 1e9 if match.group(2).lower().startswith("b") else 1e6
        revenue_actual = value * multiplier

    guidance: list[str] = []
    for tag in soup.find_all(("p", "div", "li")):
        text = _normalize_text(tag.get_text(" ", strip=True))
        if not any(term in text.lower() for term in _GUIDANCE_TERMS):
            continue
        if 25 < len(text) < 300 and text not in guidance:
            guidance.append(text)
        if len(guidance) == 2:
            break

    return revenue_actual, " | ".join(guidance) if guidance else None


__all__ = ["parse_earnings_release"]
