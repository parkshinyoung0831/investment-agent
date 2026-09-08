"""SEC HTML 표를 병합 셀·표시 단위까지 반영해 읽는 경량 파서."""
from __future__ import annotations

import math
import re
from typing import Any

from bs4 import BeautifulSoup

_UNIT_RE = re.compile(
    r"(?:in\s+|\$\s*|usd\s+)?(billions?|millions?|thousands?)\b|\$\s*0{3,6}\b",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"\(?\s*-?\s*(?:\$|USD\s*)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*\)?",
    re.IGNORECASE,
)
_LABELS: dict[str, tuple[str, int]] = {
    "revenue": ("revenue", 70),
    "total revenue": ("revenue", 75),
    "total revenues": ("revenue", 75),
    "net revenue": ("revenue", 72),
    "net revenues": ("revenue", 72),
    "net sales": ("revenue", 74),
    "total net sales": ("revenue", 76),
    "sales": ("revenue", 60),
    "total sales": ("revenue", 65),
    "operating income": ("operating_income", 80),
    "income from operations": ("operating_income", 82),
    "operating profit": ("operating_income", 78),
    "operating earnings": ("operating_income", 78),
    "net income": ("net_income", 80),
    "net income loss": ("net_income", 82),
    "consolidated net income": ("net_income", 84),
    "net earnings": ("net_income", 76),
    "net profit": ("net_income", 74),
}
_PER_SHARE_RE = re.compile(r"per\s+share|diluted|basic|margin|percentage|growth|change", re.IGNORECASE)
_QUARTER_RE = re.compile(r"three\s+months|quarter(?:ly)?|13\s+weeks|14\s+weeks", re.IGNORECASE)
_CUMULATIVE_RE = re.compile(r"six\s+months|nine\s+months|year\s+ended|full\s+year|fiscal\s+year", re.IGNORECASE)
_TEXT_AMOUNT_RE = re.compile(
    r"\b(revenue|net\s+sales|operating\s+income|income\s+from\s+operations|net\s+income|net\s+earnings)\b"
    r"[^.!?]{0,35}?\b(?:was|were|of|totaled|reached|increased\s+to)\b\s*"
    r"(?:\$|USD\s*)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(billion|million|thousand)s?\b",
    re.IGNORECASE,
)


def _text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _normalized_label(value: object) -> str:
    return " ".join(re.sub(r"[^a-z]+", " ", _text(value).lower()).split())


def normalize_table(table: Any) -> list[list[str]]:
    """rowspan·colspan을 펼친 표 행렬을 반환한다."""
    if isinstance(table, str):
        table = BeautifulSoup(table, "html.parser").find("table")
    if table is None:
        return []
    rows = [
        row for row in table.find_all("tr")
        if row.find_parent("table") is table
    ]
    grid: list[list[str | None]] = []
    for row_index, row_tag in enumerate(rows):
        while len(grid) <= row_index:
            grid.append([])
        cells = row_tag.find_all(("th", "td"), recursive=False)
        if not cells:
            cells = row_tag.find_all(("th", "td"))
        column = 0
        for cell in cells:
            while column < len(grid[row_index]) and grid[row_index][column] is not None:
                column += 1
            try:
                rowspan = max(1, int(cell.get("rowspan", 1)))
            except (TypeError, ValueError):
                rowspan = 1
            try:
                colspan = max(1, int(cell.get("colspan", 1)))
            except (TypeError, ValueError):
                colspan = 1
            value = _text(cell.get_text(" ", strip=True))
            for row_offset in range(rowspan):
                target_row = row_index + row_offset
                while len(grid) <= target_row:
                    grid.append([])
                while len(grid[target_row]) < column + colspan:
                    grid[target_row].append(None)
                for col_offset in range(colspan):
                    target_column = column + col_offset
                    if grid[target_row][target_column] is None:
                        grid[target_row][target_column] = value
            column += colspan
    width = max((len(row) for row in grid), default=0)
    return [[str(value or "") for value in row] + [""] * (width - len(row)) for row in grid]


def _unit_multiplier(table: Any) -> float:
    """표 제목과 캡션의 표시 단위를 달러 배수로 바꾼다."""
    contexts = [_text(table.get("summary") if hasattr(table, "get") else "")]
    caption = table.find("caption") if hasattr(table, "find") else None
    if caption is not None:
        contexts.append(_text(caption.get_text(" ", strip=True)))
    # SEC 표는 단위를 caption이 아니라 표 첫 행에 넣는 경우가 많다
    # (예: ``(Amounts in millions)`` 또는 ``$ Millions``).
    if hasattr(table, "get_text"):
        contexts.append(_text(table.get_text(" ", strip=True))[:2000])
    if hasattr(table, "find_all_previous"):
        contexts.extend(
            _text(tag.get_text(" ", strip=True))
            for tag in table.find_all_previous(("caption", "p", "div"), limit=4)
        )
    context = " ".join(contexts).lower()
    match = _UNIT_RE.search(context)
    if not match:
        return 1.0
    unit = match.group(1) or "thousands"
    if unit.startswith("billion"):
        return 1e9
    if unit.startswith("million"):
        return 1e6
    return 1e3


def parse_amount(value: object, *, multiplier: float = 1.0) -> float | None:
    """금액 셀 하나를 정수 달러 값으로 바꾼다."""
    raw = _text(value)
    if not raw or raw in {"-", "—", "–", "nm", "n/a", "na"}:
        return None
    if "%" in raw or _PER_SHARE_RE.search(raw) or re.search(r"\b(?:to|low|high)\b", raw, re.IGNORECASE):
        return None
    match = _AMOUNT_RE.search(raw.replace("−", "-"))
    if not match:
        return None
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    wrapped_parentheses = bool(re.match(r"^\s*\(.*\)\s*$", raw, re.DOTALL))
    if wrapped_parentheses or raw.lstrip().startswith("-"):
        number = -number
    number *= multiplier
    return number if math.isfinite(number) else None


def _label_at(value: object) -> tuple[str, int] | None:
    label = _normalized_label(value)
    if not label or _PER_SHARE_RE.search(label):
        return None
    exact = _LABELS.get(label)
    if exact:
        return exact
    for candidate, result in _LABELS.items():
        if label.startswith(candidate + " "):
            return result
    return None


def _labels_in_row(row: list[str]) -> list[tuple[int, str, int]]:
    """병합 셀 때문에 한 행에 반복된 레이블도 위치와 함께 보존한다."""
    out: list[tuple[int, str, int]] = []
    for index, value in enumerate(row):
        match = _label_at(value)
        if match:
            out.append((index, match[0], match[1]))
    return out


def _table_score(table_text: str, labels: set[str]) -> int:
    score = len(labels) * 25
    if _QUARTER_RE.search(table_text):
        score += 35
    if _CUMULATIVE_RE.search(table_text) and not _QUARTER_RE.search(table_text):
        score -= 20
    if re.search(r"guidance|outlook|forecast|expected|ending", table_text, re.IGNORECASE):
        score -= 45
    if re.search(r"segment|geographic|product line", table_text, re.IGNORECASE) and len(labels) < 2:
        score -= 25
    return score


def extract_summary_financials(html: str | bytes | Any) -> dict[str, float]:
    """EX-99 요약 표에서 매출·영업익·순이익의 현재 값을 추출한다."""
    if not html:
        return {}
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    if hasattr(html, "find_all"):
        soup = html
    else:
        soup = BeautifulSoup(str(html), "html.parser")
    candidates: dict[str, tuple[int, int, float]] = {}
    for table_index, table in enumerate(soup.find_all("table")):
        matrix = normalize_table(table)
        if not matrix:
            continue
        labels: dict[str, tuple[int, list[str]]] = {}
        for row_index, row in enumerate(matrix):
            row_labels = _labels_in_row(row)
            for label_index, key, label_score in row_labels:
                next_label = next(
                    (index for index, _key, _score in row_labels if index > label_index),
                    len(row),
                )
                values = row[label_index + 1:next_label]
                if any(parse_amount(value) is not None for value in values):
                    current = labels.get(key)
                    if current is None or label_score > current[0]:
                        labels[key] = (label_score, values)
        if not labels:
            continue
        context_parts = [" ".join(row) for row in matrix[:4]]
        caption = table.find("caption")
        if caption is not None:
            context_parts.append(_text(caption.get_text(" ", strip=True)))
        context_parts.extend(
            _text(tag.get_text(" ", strip=True))
            for tag in table.find_all_previous(("h1", "h2", "h3", "h4", "p", "div"), limit=2)
        )
        context = " ".join(context_parts).lower()
        table_score = _table_score(context, set(labels))
        multiplier = _unit_multiplier(table)
        for key, (label_score, values) in labels.items():
            values = [parse_amount(value, multiplier=multiplier) for value in values]
            values = [value for value in values if value is not None]
            if not values:
                continue
            # 병합된 첫 헤더를 건너뛰고도 현재 기간은 SEC 보도자료에서 대개 첫 금액이다.
            value = values[0]
            rank = table_score + label_score
            current = candidates.get(key)
            if current is None or (rank, -table_index) > (current[0], current[1]):
                candidates[key] = (rank, -table_index, value)
    result = {key: value[2] for key, value in candidates.items()}
    if len(result) < 3:
        # 표가 없는 짧은 보도자료도 놓치지 않되, 전망 문장은 was/of 계열만 허용한다.
        text = _text(soup.get_text(" ", strip=True))
        for match in _TEXT_AMOUNT_RE.finditer(text):
            label = _normalized_label(match.group(1))
            key = _LABELS.get(label, (None, 0))[0]
            if not key or key in result:
                continue
            value = parse_amount(
                match.group(2),
                multiplier={
                    "billion": 1e9,
                    "million": 1e6,
                    "thousand": 1e3,
                }[match.group(3).lower()],
            )
            if value is not None:
                result[key] = value
    return result


extract_financials = extract_summary_financials
parse_summary_financials = extract_summary_financials

__all__ = [
    "extract_financials",
    "extract_summary_financials",
    "normalize_table",
    "parse_amount",
    "parse_summary_financials",
]
