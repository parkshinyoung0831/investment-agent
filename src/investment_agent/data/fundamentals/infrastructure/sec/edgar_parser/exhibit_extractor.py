"""SEC 8-K archive에서 EX-99 보도자료를 고르고 텍스트를 정제한다."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from html import unescape

_EXHIBIT_RE = re.compile(r"(?:exhibit|ex)[-_ .]?99(?:[-_ .]?(?:1|01))?", re.IGNORECASE)
_RELEASE_RE = re.compile(
    r"(?:earnings?|results?|financial[-_ ]results?|news[-_ ]release|press[-_ ]release|release)",
    re.IGNORECASE,
)
_GUIDANCE_RE = re.compile(
    r"\b(?:guidance|outlook|forecast|expects?|expected|raises?|reaffirm(?:s|ed)?|lower(?:s|ed)?)\b",
    re.IGNORECASE,
)
_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li")
_GUIDANCE_BLOCK_TAGS = _BLOCK_TAGS + ("td", "th")
_BLOCK_SPACE_RE = re.compile(r"[ \t\r\f\v]+")


def _item_value(item: Mapping[str, object] | object, key: str) -> str:
    if isinstance(item, Mapping):
        return str(item.get(key) or "").strip()
    return str(getattr(item, key, "") or "").strip()


def _document_score(item: Mapping[str, object] | object) -> int:
    """archive 목록 한 건이 실적 보도자료일 가능성을 점수화한다."""
    name = _item_value(item, "name").lower()
    description = " ".join(
        _item_value(item, key).lower()
        for key in ("description", "type", "documentType", "title")
    )
    if not name or name.endswith((".xml", ".xsd", ".css", ".js")):
        return -100
    if any(token in name for token in ("-index", "index.html", "filingsummary")):
        return -100
    score = 0
    if _EXHIBIT_RE.search(name) or _EXHIBIT_RE.search(description):
        score += 100
    if "ex-99.1" in description or "ex-99" in description:
        score += 30
    if "press release" in description or "earnings release" in description:
        score += 25
    if _RELEASE_RE.search(name):
        score += 20
    if _RELEASE_RE.search(description):
        score += 10
    if name.endswith((".htm", ".html")):
        score += 5
    if any(token in name for token in ("graphic", "image", "logo", "map")):
        score -= 80
    return score


def select_exhibit(
    items: Iterable[Mapping[str, object] | object] | None,
    primary_document: str | None = None,
) -> Mapping[str, object] | object | None:
    """archive 파일 목록에서 가장 가능성 높은 EX-99 문서를 고른다."""
    ranked = [
        (score, -index, item)
        for index, item in enumerate(items or ())
        if (score := _document_score(item)) > 0
    ]
    if not ranked:
        if primary_document:
            fallback = {"name": str(primary_document).strip()}
            if _document_score(fallback) > 0:
                return fallback
        return None
    return max(ranked, key=lambda value: (value[0], value[1]))[2]


def extract_text(html: str | bytes | None) -> str:
    """스크립트·스타일을 제거한 사람이 읽는 공시 본문을 반환한다."""
    if not html:
        return ""
    from bs4 import BeautifulSoup

    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(("script", "style", "noscript", "svg", "template")):
        tag.decompose()
    return " ".join(_BLOCK_SPACE_RE.sub(" ", unescape(soup.get_text(" ", strip=True))).split())


def clean_html_to_markdown(html: str | bytes | None) -> str:
    """제목·문단·목록 구조를 보존한 가벼운 Markdown 블록으로 바꾼다."""
    if not html:
        return ""
    from bs4 import BeautifulSoup

    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(("script", "style", "noscript", "svg", "template")):
        tag.decompose()
    blocks: list[str] = []
    for tag in soup.find_all(_BLOCK_TAGS):
        value = " ".join(_BLOCK_SPACE_RE.sub(" ", tag.get_text(" ", strip=True)).split())
        if not value:
            continue
        if tag.name.startswith("h"):
            value = f"{'#' * int(tag.name[1:])} {value}"
        elif tag.name == "li":
            value = f"- {value}"
        if value not in blocks:
            blocks.append(value)
    return "\n\n".join(blocks)


def extract_guidance_text(html: str | bytes | None) -> str | None:
    """가이던스·전망을 언급한 원문 문단을 최대 세 개까지 연결한다."""
    if not html:
        return None
    from bs4 import BeautifulSoup

    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(("script", "style", "noscript", "svg", "template")):
        tag.decompose()
    values: list[str] = []
    for tag in soup.find_all((*_GUIDANCE_BLOCK_TAGS, "div")):
        if tag.name == "div" and tag.find(_BLOCK_TAGS):
            continue
        value = " ".join(_BLOCK_SPACE_RE.sub(" ", tag.get_text(" ", strip=True)).split())
        if not value or not _GUIDANCE_RE.search(value):
            continue
        if len(value) < 25 or len(value) > 500 or value in values:
            continue
        values.append(value)
        if len(values) == 3:
            break
    return " | ".join(values) if values else None


find_press_release = select_exhibit
extract_guidance = extract_guidance_text

__all__ = [
    "clean_html_to_markdown",
    "extract_guidance",
    "extract_guidance_text",
    "extract_text",
    "find_press_release",
    "select_exhibit",
]
